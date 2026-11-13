'use strict';
// Gemeinsames Protokoll: Verschlüsselung, Klassencode und Prüfung aller Nachrichten.
// Jede Nachricht ist mit AES-256-GCM verschlüsselt und authentifiziert.
// Der Schlüssel kommt aus dem Klassencode (scrypt). Wer den Code nicht kennt,
// kann weder mitlesen noch Nachrichten fälschen, wiederholen oder umsortieren.

const crypto = require('crypto');

const STATUSES = ['frei', 'beschaeftigt', 'frage', 'weg'];
const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // ohne 0/O, 1/I
const CODE_LENGTH = 12; // 12 Zeichen * 5 Bit = 60 Bit
const MAX_FRAME_BYTES = 4096;
const SALT = 'klassen-status-v1';

function generateCode() {
  let out = '';
  for (let i = 0; i < CODE_LENGTH; i++) out += CODE_ALPHABET[crypto.randomInt(CODE_ALPHABET.length)];
  return out.slice(0, 4) + '-' + out.slice(4, 8) + '-' + out.slice(8);
}

function normalizeCode(code) {
  if (typeof code !== 'string') return null;
  const c = code.toUpperCase().replace(/[\s-]/g, '');
  if (c.length !== CODE_LENGTH) return null;
  for (const ch of c) if (!CODE_ALPHABET.includes(ch)) return null;
  return c;
}

function deriveKey(code) {
  const c = normalizeCode(code);
  if (!c) throw new Error('Ungültiger Klassencode');
  // scrypt macht Durchprobieren von Codes sehr teuer.
  return crypto.scryptSync(c, SALT, 32, { N: 2 ** 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
}

function sessionId(serverNonce, clientNonce) {
  return crypto.createHash('sha256').update('sid|').update(serverNonce).update(clientNonce).digest();
}

// Raum-Name beim Relay: aus dem Schlüssel abgeleitet, verrät den Code nicht.
function roomId(key) {
  return crypto.createHmac('sha256', key).update('room').digest('hex');
}

// Sicherer Kanal für eine Verbindung. role = 's' (Server) oder 'c' (Client).
class SecureChannel {
  constructor(key, sid, role) {
    this.key = key;
    this.sid = sid.toString('hex');
    this.role = role;
    this.peer = role === 's' ? 'c' : 's';
    this.sendCtr = 0;
    this.recvCtr = 0;
  }

  _aad(dir, ctr) {
    return Buffer.from(`${this.sid}|${dir}|${ctr}`);
  }

  seal(obj) {
    const ctr = this.sendCtr++;
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', this.key, iv);
    cipher.setAAD(this._aad(this.role, ctr));
    const pt = Buffer.from(JSON.stringify(obj), 'utf8');
    const ct = Buffer.concat([cipher.update(pt), cipher.final()]);
    return JSON.stringify({
      n: ctr,
      iv: iv.toString('base64'),
      d: ct.toString('base64'),
      t: cipher.getAuthTag().toString('base64'),
    });
  }

  // Wirft einen Fehler, wenn irgendetwas nicht stimmt.
  open(raw, maxBytes = MAX_FRAME_BYTES) {
    const s = typeof raw === 'string' ? raw : raw.toString('utf8');
    if (s.length > maxBytes) throw new Error('zu gross');
    const f = JSON.parse(s);
    if (!f || typeof f !== 'object') throw new Error('Format');
    if (f.n !== this.recvCtr) throw new Error('Reihenfolge/Wiederholung');
    if (typeof f.iv !== 'string' || typeof f.d !== 'string' || typeof f.t !== 'string') throw new Error('Format');
    const iv = Buffer.from(f.iv, 'base64');
    const tag = Buffer.from(f.t, 'base64');
    if (iv.length !== 12 || tag.length !== 16) throw new Error('Format');
    const decipher = crypto.createDecipheriv('aes-256-gcm', this.key, iv, { authTagLength: 16 });
    decipher.setAAD(this._aad(this.peer, f.n));
    decipher.setAuthTag(tag);
    const pt = Buffer.concat([decipher.update(Buffer.from(f.d, 'base64')), decipher.final()]);
    this.recvCtr++;
    const msg = JSON.parse(pt.toString('utf8'));
    if (!msg || typeof msg !== 'object' || Array.isArray(msg) || typeof msg.type !== 'string') throw new Error('Format');
    return msg;
  }
}

// Namen: 1–24 Zeichen, nur Buchstaben, Zahlen, Leerzeichen und . - _
function cleanName(name) {
  if (typeof name !== 'string') return null;
  const n = name.normalize('NFC').replace(/\s+/g, ' ').trim();
  if (n.length < 1 || n.length > 24) return null;
  if (!/^[\p{L}\p{N} ._-]+$/u.test(n)) return null;
  return n;
}

function isStatus(s) {
  return typeof s === 'string' && STATUSES.includes(s);
}

// Relay-Adresse: nur wss:// (verschlüsselt). ws:// nur für localhost (Tests).
function cleanRelayUrl(url) {
  if (typeof url !== 'string' || url.length > 300) return null;
  let u;
  try { u = new URL(url.trim()); } catch { return null; }
  const local = u.hostname === 'localhost' || u.hostname === '127.0.0.1';
  if (!(u.protocol === 'wss:' || (u.protocol === 'ws:' && local))) return null;
  if (u.username || u.password || u.search || u.hash) return null;
  return `${u.protocol}//${u.host}${u.pathname.replace(/\/+$/, '')}`;
}

// Einfacher Zähler gegen Spam: höchstens `max` Ereignisse in `ms` Millisekunden.
class RateLimiter {
  constructor(max, ms) {
    this.max = max;
    this.ms = ms;
    this.times = [];
  }
  allow(now = Date.now()) {
    this.times = this.times.filter((t) => now - t < this.ms);
    if (this.times.length >= this.max) return false;
    this.times.push(now);
    return true;
  }
}

module.exports = {
  STATUSES, MAX_FRAME_BYTES,
  generateCode, normalizeCode, deriveKey, sessionId, roomId, cleanRelayUrl,
  SecureChannel, cleanName, isStatus, RateLimiter,
};
