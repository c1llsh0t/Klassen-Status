'use strict';
// Das "Gehirn" der Klasse läuft in der App des Admins.
// Die Verbindung geht über einen Relay-Server im Internet (funktioniert auch
// mit Handy-Hotspot). Der Relay sieht nur verschlüsselte Daten.

const crypto = require('crypto');
const WebSocket = require('ws');
const P = require('./protocol');

const MAX_MEMBERS = 100;
const HANDSHAKE_TIMEOUT_MS = 10000;
const HELP_NOTIFY_COOLDOWN_MS = 15000;

class ClassServer {
  /**
   * @param {object} opts
   * @param {string} opts.adminName
   * @param {string} opts.code        Klassencode
   * @param {string} opts.relayUrl   z.B. wss://klassen-status.onrender.com
   * @param {(state:string)=>void} [opts.onConnState]
   * @param {(roster:any[])=>void} [opts.onRoster]
   * @param {(name:string)=>void} [opts.onHelp]
   */
  constructor(opts) {
    this.adminName = P.cleanName(opts.adminName);
    if (!this.adminName) throw new Error('Ungültiger Name');
    this.code = opts.code;
    this.key = P.deriveKey(opts.code);
    this.relayUrl = opts.relayUrl;
    this.onConnState = opts.onConnState || (() => {});
    this.conns = new Map(); // peerId -> virtuelle Verbindung
    this.stopped = false;
    this.backoff = 1000;
    this.onRoster = opts.onRoster || (() => {});
    this.onHelp = opts.onHelp || (() => {});
    this.locked = false;
    this.members = new Map();
    this.members.set('admin', {
      id: 'admin', name: this.adminName, status: 'frei', online: true, isAdmin: true,
    });
  }

  // Verbindet sich als "host" mit dem Relay. Löst aus, sobald verbunden
  // (oder mit Fehler, falls der Code schon von einer anderen Admin-App benutzt wird).
  start() {
    return new Promise((resolve, reject) => {
      this._firstConnect = { resolve, reject };
      this._connectRelay();
    });
  }

  _connectRelay() {
    if (this.stopped) return;
    this.onConnState('verbinde');
    const url = `${this.relayUrl}/?room=${P.roomId(this.key)}&role=host`;
    const ws = new WebSocket(url, { maxPayload: 64 * 1024, perMessageDeflate: false, handshakeTimeout: 15000 });
    this.relay = ws;
    ws.on('open', () => {
      ws.pingTimer = setInterval(() => { try { ws.ping(); } catch { /* egal */ } }, 20000);
    });
    ws.on('message', (data) => this._onRelayMessage(data));
    ws.on('error', () => {});
    ws.on('close', (code) => {
      clearInterval(ws.pingTimer);
      // Alle Schüler-Verbindungen sind damit weg.
      for (const conn of [...this.conns.values()]) this._onPeerClose(conn);
      if (this.stopped) return;
      if (code === 4009) {
        this.onConnState('doppelt');
        const err = new Error('Dieser Klassencode ist schon bei einer anderen Admin-App aktiv.');
        if (this._firstConnect) { this._firstConnect.reject(err); this._firstConnect = null; this.stopped = true; return; }
      } else {
        this.onConnState('getrennt');
      }
      setTimeout(() => this._connectRelay(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 30000);
    });
  }

  stop() {
    this.stopped = true;
    if (this.relay) this.relay.terminate();
    return Promise.resolve();
  }

  _onRelayMessage(data) {
    let m;
    try { m = JSON.parse(data.toString('utf8')); } catch { return; }
    if (m && m.ev === 'ready') {
      this.backoff = 1000;
      this.onConnState('online');
      if (this._firstConnect) { this._firstConnect.resolve(); this._firstConnect = null; }
      return;
    }
    if (!m || typeof m.peer !== 'string' || m.peer.length > 64) return;
    if (m.ev === 'open') {
      if (this.conns.size >= MAX_MEMBERS + 20) { this._relaySend({ to: m.peer, f: '', close: true }); return; }
      this._onPeerOpen(m.peer);
    } else if (m.ev === 'msg' && typeof m.d === 'string') {
      const conn = this.conns.get(m.peer);
      if (conn) this._onPeerMessage(conn, m.d);
    } else if (m.ev === 'close') {
      const conn = this.conns.get(m.peer);
      if (conn) this._onPeerClose(conn);
    }
  }

  _relaySend(obj) {
    if (this.relay && this.relay.readyState === 1) this.relay.send(JSON.stringify(obj));
  }

  // ---- Aktionen des Admins (kommen direkt aus der eigenen App) ----

  setAdminStatus(status) {
    if (!P.isStatus(status)) return;
    this.members.get('admin').status = status;
    this._broadcastRoster();
  }

  callMember(id) {
    const m = this.members.get(id);
    if (!m || m.isAdmin || !m.online || !m.conn) return false;
    this._send(m.conn, { type: 'come', from: this.adminName });
    return true;
  }

  clearQuestion(id) {
    const m = this.members.get(id);
    if (!m || m.isAdmin) return;
    if (m.status === 'frage') {
      m.status = m.online ? 'frei' : 'weg';
      if (m.conn) this._send(m.conn, { type: 'status', status: m.status });
      this._broadcastRoster();
    }
  }

  removeMember(id) {
    const m = this.members.get(id);
    if (!m || m.isAdmin) return;
    if (m.conn) {
      const conn = m.conn;
      this._send(conn, { type: 'removed' });
      m.conn = null;
      setTimeout(() => conn.close(), 50);
    }
    this.members.delete(id);
    this._broadcastRoster();
  }

  setLocked(locked) {
    this.locked = !!locked;
    this._broadcastRoster();
  }

  roster() {
    return [...this.members.values()].map((m) => ({
      id: m.id, name: m.name, status: m.status, online: m.online, isAdmin: !!m.isAdmin,
    }));
  }

  static localAddresses() {
    const out = [];
    for (const list of Object.values(os.networkInterfaces())) {
      for (const a of list || []) {
        if (a.family === 'IPv4' && !a.internal) out.push(a.address);
      }
    }
    return out;
  }

  // ---- Netzwerk ----

  _onPeerOpen(peer) {
    const serverNonce = crypto.randomBytes(16);
    const conn = {
      peer, serverNonce, channel: null, memberId: null, closed: false,
      limiter: new P.RateLimiter(20, 10000),
      send: (str) => this._relaySend({ to: peer, f: str }),
      close: () => { if (!conn.closed) { this._relaySend({ to: peer, f: '', close: true }); this._onPeerClose(conn); } },
    };
    conn.timer = setTimeout(() => { if (!conn.channel || !conn.memberId) conn.close(); }, HANDSHAKE_TIMEOUT_MS);
    this.conns.set(peer, conn);
    conn.send(JSON.stringify({ type: 'hello', v: 1, sn: serverNonce.toString('base64') }));
  }

  _onPeerMessage(conn, data) {
    if (conn.closed) return;
    if (!conn.limiter.allow()) { conn.close(); return; }
    try {
      if (!conn.channel) {
        // Erste Nachricht: { cn, f } – f ist bereits verschlüsselt.
        if (data.length > P.MAX_FRAME_BYTES) throw new Error('zu gross');
        const first = JSON.parse(data);
        const cn = Buffer.from(String(first.cn || ''), 'base64');
        if (cn.length !== 16 || typeof first.f !== 'string') throw new Error('Format');
        conn.channel = new P.SecureChannel(this.key, P.sessionId(conn.serverNonce, cn), 's');
        const msg = conn.channel.open(first.f);
        clearTimeout(conn.timer);
        this._handleJoin(conn, msg);
      } else {
        this._handleMessage(conn, conn.channel.open(data));
      }
    } catch {
      // Falscher Code, Manipulation oder Unsinn → Verbindung sofort trennen.
      conn.close();
    }
  }

  _onPeerClose(conn) {
    if (conn.closed) return;
    conn.closed = true;
    clearTimeout(conn.timer);
    this.conns.delete(conn.peer);
    const m = conn.memberId && this.members.get(conn.memberId);
    if (m && m.conn === conn) {
      m.conn = null;
      m.online = false;
      m.status = 'weg';
      this._broadcastRoster();
    }
  }

  _reject(conn, reason) {
    this._send(conn, { type: 'rejected', reason });
    setTimeout(() => conn.close(), 50);
  }

  _handleJoin(conn, msg) {
    if (msg.type !== 'join') throw new Error('erwartet join');
    const name = P.cleanName(msg.name);
    if (!name) return this._reject(conn, 'Ungültiger Name.');

    const key = name.toLocaleLowerCase('de');
    let member = [...this.members.values()].find((m) => m.name.toLocaleLowerCase('de') === key);

    if (member) {
      if (member.isAdmin) return this._reject(conn, 'Dieser Name gehört dem Admin.');
      if (member.online) return this._reject(conn, 'Dieser Name ist schon online.');
    } else {
      if (this.locked) return this._reject(conn, 'Die Klasse ist geschlossen.');
      if (this.members.size >= MAX_MEMBERS) return this._reject(conn, 'Die Klasse ist voll.');
      member = { id: crypto.randomUUID(), name, status: 'frei', online: false, isAdmin: false };
      this.members.set(member.id, member);
    }

    member.online = true;
    member.status = 'frei';
    member.conn = conn;
    member.lastHelp = 0;
    conn.memberId = member.id;
    this._send(conn, { type: 'welcome', id: member.id, admin: this.adminName });
    this._broadcastRoster();
  }

  _handleMessage(conn, msg) {
    const m = this.members.get(conn.memberId);
    if (!m || m.conn !== conn) throw new Error('kein Mitglied');
    switch (msg.type) {
      case 'status': {
        if (!P.isStatus(msg.status)) throw new Error('Status');
        if (m.status === msg.status) return;
        m.status = msg.status;
        if (msg.status === 'frage') {
          const now = Date.now();
          if (now - m.lastHelp > HELP_NOTIFY_COOLDOWN_MS) {
            m.lastHelp = now;
            this.onHelp(m.name);
          }
        }
        this._broadcastRoster();
        return;
      }
      case 'ping':
        return;
      default:
        throw new Error('unbekannt');
    }
  }

  _send(conn, obj) {
    if (!conn || !conn.channel || conn.closed) return;
    try { conn.send(conn.channel.seal(obj)); } catch { /* egal */ }
  }

  _broadcastRoster() {
    const roster = this.roster();
    const payload = { type: 'roster', members: roster, locked: this.locked };
    for (const m of this.members.values()) {
      if (m.conn) this._send(m.conn, payload);
    }
    this.onRoster(roster, this.locked);
  }
}

module.exports = { ClassServer };
