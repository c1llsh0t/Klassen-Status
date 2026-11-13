'use strict';
// Läuft in der App der Schüler. Verbindet sich über den Relay mit der Admin-App.

const crypto = require('crypto');
const { EventEmitter } = require('events');
const WebSocket = require('ws');
const P = require('./protocol');

const MAX_INBOUND = 64 * 1024;

class ClassClient extends EventEmitter {
  /**
   * Events: 'state' (verbinde|online|getrennt|kein-admin), 'roster' (members, locked),
   * 'come' (fromName), 'status' (status), 'rejected' (reason), 'removed', 'wrong-code'
   */
  constructor({ relayUrl, name, code }) {
    super();
    this.relayUrl = relayUrl;
    this.name = P.cleanName(name);
    if (!this.name) throw new Error('Ungültiger Name');
    this.key = P.deriveKey(code);
    this.room = P.roomId(this.key);
    this.stopped = false;
    this.backoff = 1000;
    this.myStatus = 'frei';
  }

  start() { this._connect(); }

  stop() {
    this.stopped = true;
    clearTimeout(this.retry);
    if (this.ws) this.ws.terminate();
  }

  setStatus(status) {
    if (!P.isStatus(status)) return;
    this.myStatus = status;
    this._send({ type: 'status', status });
  }

  _connect() {
    if (this.stopped) return;
    this.emit('state', 'verbinde');
    const ws = new WebSocket(`${this.relayUrl}/?room=${this.room}&role=peer`, {
      maxPayload: MAX_INBOUND, perMessageDeflate: false, handshakeTimeout: 15000,
    });
    this.ws = ws;
    this.channel = null;
    this.ready = false;
    let gotHello = false;
    let welcomed = false;
    let finalReason = null;

    // Kommt keine gültige Antwort, ist wahrscheinlich der Code falsch.
    const handshakeTimer = setTimeout(() => { if (!welcomed) { finalReason = 'timeout'; ws.terminate(); } }, 15000);

    ws.on('message', (data, isBinary) => {
      if (isBinary) { ws.terminate(); return; }
      try {
        if (!gotHello) {
          const hello = JSON.parse(data.toString('utf8'));
          const sn = Buffer.from(String(hello.sn || ''), 'base64');
          if (hello.type !== 'hello' || sn.length !== 16) throw new Error('hello');
          gotHello = true;
          const cn = crypto.randomBytes(16);
          this.channel = new P.SecureChannel(this.key, P.sessionId(sn, cn), 'c');
          ws.send(JSON.stringify({ cn: cn.toString('base64'), f: this.channel.seal({ type: 'join', name: this.name }) }));
          return;
        }
        const msg = this.channel.open(data, MAX_INBOUND);
        if (!welcomed) {
          if (msg.type === 'rejected') { finalReason = 'rejected'; this._final('rejected', String(msg.reason || '').slice(0, 100)); return; }
          if (msg.type !== 'welcome' || typeof msg.id !== 'string') throw new Error('welcome');
          welcomed = true;
          clearTimeout(handshakeTimer);
          this.myId = msg.id;
          this.adminName = P.cleanName(msg.admin) || 'Admin';
          this.ready = true;
          this.backoff = 1000;
          this.emit('state', 'online');
          // Eigenen Status nach Wiederverbindung wiederherstellen.
          if (this.myStatus !== 'frei') this._send({ type: 'status', status: this.myStatus });
          return;
        }
        this._handle(msg);
      } catch {
        // Entschlüsselung fehlgeschlagen → falscher Code oder Manipulation.
        if (gotHello && !welcomed) finalReason = 'wrong-code';
        ws.terminate();
      }
    });

    ws.on('error', () => {});
    ws.on('close', (code) => {
      clearTimeout(handshakeTimer);
      this.ready = false;
      if (this.stopped) return;
      if (finalReason === 'rejected' || finalReason === 'removed') return;
      if (finalReason === 'wrong-code' || (gotHello && !welcomed && code === 4000)) {
        // Admin hat uns sofort getrennt: Code passt nicht.
        this.stopped = true;
        this.emit('wrong-code');
        return;
      }
      this.emit('state', code === 4004 ? 'kein-admin' : 'getrennt');
      this.retry = setTimeout(() => this._connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 15000);
    });
  }

  _final(event, arg) {
    this.stopped = true;
    this.emit(event, arg);
    if (this.ws) this.ws.close();
  }

  _handle(msg) {
    switch (msg.type) {
      case 'roster': {
        if (!Array.isArray(msg.members) || msg.members.length > 200) return;
        const members = [];
        for (const m of msg.members) {
          if (!m || typeof m.id !== 'string' || m.id.length > 64) continue;
          const name = P.cleanName(m.name);
          if (!name || !P.isStatus(m.status)) continue;
          members.push({ id: m.id, name, status: m.status, online: !!m.online, isAdmin: !!m.isAdmin, me: m.id === this.myId });
        }
        this.emit('roster', members, !!msg.locked);
        return;
      }
      case 'come':
        this.emit('come', P.cleanName(msg.from) || this.adminName);
        return;
      case 'status':
        if (P.isStatus(msg.status)) { this.myStatus = msg.status; this.emit('status', msg.status); }
        return;
      case 'removed':
        this._final('removed');
        return;
      default:
        // Unbekannte Nachrichten ignorieren.
    }
  }

  _send(obj) {
    if (!this.ready || !this.channel || this.ws.readyState !== 1) return;
    try { this.ws.send(this.channel.seal(obj)); } catch { /* egal */ }
  }
}

module.exports = { ClassClient };
