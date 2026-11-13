'use strict';
// Relay-Server: leitet nur verschlüsselte Nachrichten zwischen Admin-App und
// Schüler-Apps weiter. Er kennt den Klassencode NICHT und kann nichts lesen.
// Läuft z.B. gratis auf Render.com (siehe README).

const http = require('http');
const crypto = require('crypto');
const { WebSocketServer } = require('ws');

const PORT = Number(process.env.PORT) || 8080;
const MAX_ROOMS = 2000;
const MAX_PEERS_PER_ROOM = 100;
const MAX_CONNS_PER_IP = 150; // ganze Klasse kann hinter einer Schul-IP sein
const PEER_MAX_BYTES = 4096;
const HOST_MAX_BYTES = 64 * 1024;
const HEARTBEAT_MS = 25000;

const rooms = new Map(); // roomId -> { host, peers: Map<peerId, ws> }
const perIp = new Map();

function limiter(max, ms) {
  let times = [];
  return () => {
    const now = Date.now();
    times = times.filter((t) => now - t < ms);
    if (times.length >= max) return false;
    times.push(now);
    return true;
  };
}

const server = http.createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'x-content-type-options': 'nosniff' });
  res.end('Klassen-Status Relay läuft.\n');
});

const wss = new WebSocketServer({ noServer: true, maxPayload: HOST_MAX_BYTES, perMessageDeflate: false });

server.on('upgrade', (req, socket, head) => {
  let url;
  try { url = new URL(req.url, 'http://x'); } catch { socket.destroy(); return; }
  const room = url.searchParams.get('room') || '';
  const role = url.searchParams.get('role') || '';
  if (!/^[0-9a-f]{64}$/.test(room) || (role !== 'host' && role !== 'peer')) { socket.destroy(); return; }

  // Hinter dem Render-Proxy: der letzte x-forwarded-for Eintrag kommt vom Proxy selbst
  // (die vorderen könnte ein Angreifer fälschen).
  const ip = String(req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').split(',').pop().trim();
  if ((perIp.get(ip) || 0) >= MAX_CONNS_PER_IP) { socket.destroy(); return; }

  wss.handleUpgrade(req, socket, head, (ws) => {
    perIp.set(ip, (perIp.get(ip) || 0) + 1);
    ws.on('close', () => {
      const n = (perIp.get(ip) || 1) - 1;
      if (n <= 0) perIp.delete(ip); else perIp.set(ip, n);
    });
    ws.on('error', () => {});
    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; });
    if (role === 'host') onHost(ws, room); else onPeer(ws, room);
  });
});

function onHost(ws, roomId) {
  let room = rooms.get(roomId);
  if (room && room.host) { ws.close(4009, 'host-exists'); return; }
  if (!room) {
    if (rooms.size >= MAX_ROOMS) { ws.close(4029, 'full'); return; }
    room = { host: null, peers: new Map() };
    rooms.set(roomId, room);
  }
  room.host = ws;
  ws.send(JSON.stringify({ ev: 'ready' }));
  const allow = limiter(400, 10000);

  ws.on('message', (data, isBinary) => {
    if (isBinary || !allow()) { ws.terminate(); return; }
    let m;
    try { m = JSON.parse(data.toString('utf8')); } catch { ws.terminate(); return; }
    if (!m || typeof m.to !== 'string' || typeof m.f !== 'string') { ws.terminate(); return; }
    const peer = room.peers.get(m.to);
    if (!peer || peer.readyState !== 1) return;
    if (m.close === true) { peer.close(4000, 'closed-by-host'); return; }
    peer.send(m.f);
  });

  ws.on('close', () => {
    if (room.host !== ws) return;
    room.host = null;
    for (const p of room.peers.values()) p.close(4004, 'no-host');
    room.peers.clear();
    rooms.delete(roomId);
  });
}

function onPeer(ws, roomId) {
  const room = rooms.get(roomId);
  if (!room || !room.host || room.host.readyState !== 1) { ws.close(4004, 'no-host'); return; }
  if (room.peers.size >= MAX_PEERS_PER_ROOM) { ws.close(4029, 'full'); return; }

  const id = crypto.randomUUID();
  room.peers.set(id, ws);
  const allow = limiter(20, 10000);
  const hostSend = (obj) => { if (room.host && room.host.readyState === 1) room.host.send(JSON.stringify(obj)); };
  hostSend({ ev: 'open', peer: id });

  ws.on('message', (data, isBinary) => {
    if (isBinary || data.length > PEER_MAX_BYTES || !allow()) { ws.terminate(); return; }
    hostSend({ ev: 'msg', peer: id, d: data.toString('utf8') });
  });
  ws.on('close', () => {
    if (room.peers.get(id) === ws) {
      room.peers.delete(id);
      hostSend({ ev: 'close', peer: id });
    }
  });
}

const hb = setInterval(() => {
  for (const ws of wss.clients) {
    if (!ws.isAlive) { ws.terminate(); continue; }
    ws.isAlive = false;
    try { ws.ping(); } catch { /* egal */ }
  }
}, HEARTBEAT_MS);

if (require.main === module) {
  server.listen(PORT, () => console.log(`Relay hört auf Port ${PORT}`));
}

module.exports = {
  server,
  listen(port = 0) {
    return new Promise((r) => server.listen(port, '127.0.0.1', () => r(server.address().port)));
  },
  close() {
    clearInterval(hb);
    for (const ws of wss.clients) ws.terminate();
    return new Promise((r) => server.close(() => r()));
  },
};
