'use strict';
const test = require('node:test');
const assert = require('node:assert');
const WebSocket = require('ws');
const P = require('../src/protocol');
const { ClassServer } = require('../src/server');
const { ClassClient } = require('../src/client');
const relay = require('../relay/relay');

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function once(em, ev, ms = 5000) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('timeout ' + ev)), ms);
    em.once(ev, (...a) => { clearTimeout(t); res(a); });
  });
}

function untilState(c, want, ms = 5000) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('timeout state ' + want)), ms);
    const h = (s) => { if (s === want) { clearTimeout(t); c.off('state', h); res(); } };
    c.on('state', h);
  });
}

let relayUrl;
test.before(async () => { relayUrl = `ws://127.0.0.1:${await relay.listen(0)}`; });
test.after(() => relay.close());

test('Protokoll: Code, Namen, URL', () => {
  const c = P.generateCode();
  assert.match(c, /^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  assert.ok(P.normalizeCode(c.toLowerCase()));
  assert.equal(P.normalizeCode('abc'), null);
  assert.equal(P.cleanName('<img src=x onerror=alert(1)>'), null);
  assert.equal(P.cleanName('  Lena   M. '), 'Lena M.');
  assert.equal(P.cleanName('x'.repeat(25)), null);
  assert.equal(P.cleanRelayUrl('ws://evil.com'), null);
  assert.equal(P.cleanRelayUrl('wss://a.onrender.com/'), 'wss://a.onrender.com');
  assert.equal(P.cleanRelayUrl('javascript:alert(1)'), null);
});

test('Kanal: Manipulation und Wiederholung werden erkannt', () => {
  const key = P.deriveKey(P.generateCode());
  const sid = Buffer.alloc(32, 1);
  const a = new P.SecureChannel(key, sid, 'c');
  const b = new P.SecureChannel(key, sid, 's');
  const f1 = a.seal({ type: 'x', v: 1 });
  assert.deepEqual(b.open(f1), { type: 'x', v: 1 });
  assert.throws(() => b.open(f1)); // Wiederholung
  const f2 = JSON.parse(a.seal({ type: 'x' }));
  f2.d = Buffer.from('kaputt').toString('base64');
  assert.throws(() => b.open(JSON.stringify(f2))); // verändert
  const other = new P.SecureChannel(P.deriveKey(P.generateCode()), sid, 's');
  assert.throws(() => other.open(a.seal({ type: 'y' }))); // falscher Code
  // Eigene Nachricht zurückspiegeln geht nicht (Richtung im AAD)
  const c2 = new P.SecureChannel(key, sid, 'c');
  const echo = new P.SecureChannel(key, sid, 'c');
  assert.throws(() => c2.open(echo.seal({ type: 'z' })));
});

test('Ganzer Ablauf: Beitreten, Hilfe, Rufen, Schliessen, Entfernen', async () => {
  const code = P.generateCode();
  const helps = [];
  const server = new ClassServer({ adminName: 'Frau Meier', code, relayUrl, onHelp: (n) => helps.push(n) });
  await server.start();

  const lena = new ClassClient({ relayUrl, name: 'Lena', code });
  const tim = new ClassClient({ relayUrl, name: 'Tim', code });
  const ready = Promise.all([untilState(lena, 'online'), untilState(tim, 'online')]);
  lena.start(); tim.start();
  await ready;
  await wait(200);
  assert.deepEqual(server.roster().map((m) => m.name).sort(), ['Frau Meier', 'Lena', 'Tim']);

  // Lena sieht alle
  const [members] = await (async () => { const p = once(lena, 'roster'); tim.setStatus('beschaeftigt'); return p; })();
  assert.equal(members.find((m) => m.name === 'Tim').status, 'beschaeftigt');
  assert.ok(members.find((m) => m.name === 'Lena').me);

  // Hilfe → Admin bekommt Meldung
  lena.setStatus('frage');
  await wait(200);
  assert.deepEqual(helps, ['Lena']);
  // Spam wird gebremst
  lena.setStatus('frei'); lena.setStatus('frage');
  await wait(200);
  assert.deepEqual(helps, ['Lena']);

  // Admin ruft Tim
  const timId = server.roster().find((m) => m.name === 'Tim').id;
  const comeP = once(tim, 'come');
  assert.ok(server.callMember(timId));
  assert.deepEqual(await comeP, ['Frau Meier']);

  // Geschlossen: Neue dürfen nicht rein
  server.setLocked(true);
  const neu = new ClassClient({ relayUrl, name: 'Neu', code });
  const rej = once(neu, 'rejected');
  neu.start();
  assert.match((await rej)[0], /geschlossen/);

  // Gleicher Name doppelt geht nicht
  server.setLocked(false);
  const fake = new ClassClient({ relayUrl, name: 'lena', code });
  const rej2 = once(fake, 'rejected');
  fake.start();
  assert.match((await rej2)[0], /schon online/);

  // Falscher Code
  const wrong = new ClassClient({ relayUrl, name: 'Hacker', code: P.generateCode() });
  // falscher Code ergibt anderen Raum → kein Admin
  const noAdmin = untilState(wrong, 'kein-admin');
  wrong.start();
  await noAdmin;
  wrong.stop();

  // Entfernen
  const rem = once(tim, 'removed');
  server.removeMember(timId);
  await rem;
  await wait(100);
  assert.ok(!server.roster().some((m) => m.name === 'Tim'));

  lena.stop();
  await wait(200);
  const l = server.roster().find((m) => m.name === 'Lena');
  assert.equal(l.online, false);
  assert.equal(l.status, 'weg');
  await server.stop();
});

test('Angriffe: Raum mit falschen Daten, falsche erste Nachricht, Riesen-Nachricht', async () => {
  const code = P.generateCode();
  const server = new ClassServer({ adminName: 'Admin', code, relayUrl });
  await server.start();
  const room = P.roomId(P.deriveKey(code));

  // Jemand kennt den Raum (z.B. Relay-Betreiber), aber nicht den Code
  const ws = new WebSocket(`${relayUrl}/?room=${room}&role=peer`);
  const closed = new Promise((r) => ws.on('close', (c) => r(c)));
  ws.on('message', () => ws.send(JSON.stringify({ cn: Buffer.alloc(16).toString('base64'), f: '{"n":0,"iv":"AAAAAAAAAAAAAAAA","d":"","t":"AAAAAAAAAAAAAAAAAAAAAA=="}' })));
  assert.equal(await closed, 4000);
  assert.equal(server.roster().length, 1);

  // Riesen-Nachricht
  const ws2 = new WebSocket(`${relayUrl}/?room=${room}&role=peer`);
  const closed2 = new Promise((r) => ws2.on('close', (c) => r(c)));
  ws2.on('message', () => ws2.send('x'.repeat(10000)));
  assert.notEqual(await closed2, 1000);

  // Zweite Admin-App mit gleichem Code
  const dup = new ClassServer({ adminName: 'Admin2', code, relayUrl });
  await assert.rejects(dup.start(), /schon/);

  // Ungültiger Raum
  const ws3 = new WebSocket(`${relayUrl}/?room=abc&role=peer`);
  await new Promise((r) => ws3.on('error', r));
  await server.stop();
});
