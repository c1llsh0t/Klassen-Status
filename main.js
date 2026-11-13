'use strict';
const { app, BrowserWindow, ipcMain, Notification, Menu, session, safeStorage, clipboard, protocol } = require('electron');
const path = require('path');
const fs = require('fs');
const P = require('./src/protocol');
const { ClassServer } = require('./src/server');
const { ClassClient } = require('./src/client');
const { DEFAULT_RELAY_URL } = require('./src/config');

app.setAppUserModelId('ch.klasse.klassenstatus');

// Eigene, abgeschottete Adresse für die Oberfläche: app://klasse/...
// Es werden nur die drei Dateien aus renderer/ ausgeliefert, sonst nichts.
protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true } }]);
const PAGE_URL = 'app://klasse/index.html';
const RENDERER_FILES = {
  '/index.html': 'text/html; charset=utf-8',
  '/style.css': 'text/css; charset=utf-8',
  '/app.js': 'text/javascript; charset=utf-8',
};
const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'";
if (!app.requestSingleInstanceLock()) { app.quit(); }

let win = null;
let server = null; // nur Admin
let client = null; // nur Schüler
let mode = null;   // 'admin' | 'student'
let currentCode = null;

// ---------- Einstellungen (Klassencode wird verschlüsselt gespeichert) ----------
const settingsFile = () => path.join(app.getPath('userData'), 'einstellungen.json');

async function loadSettings() {
  try {
    const s = JSON.parse(fs.readFileSync(settingsFile(), 'utf8'));
    let code = null;
    if (typeof s.codeEnc === 'string' && await safeStorage.isAsyncEncryptionAvailable()) {
      try { code = (await safeStorage.decryptStringAsync(Buffer.from(s.codeEnc, 'base64'))).result; } catch { code = null; }
    }
    return {
      name: P.cleanName(s.name) || '',
      relayUrl: P.cleanRelayUrl(s.relayUrl) || DEFAULT_RELAY_URL,
      lastMode: s.lastMode === 'admin' ? 'admin' : 'student',
      code: P.normalizeCode(code) ? code : null,
      alwaysOnTop: !!s.alwaysOnTop,
    };
  } catch {
    return { name: '', relayUrl: DEFAULT_RELAY_URL, lastMode: 'student', code: null, alwaysOnTop: false };
  }
}

async function saveSettings(patch) {
  const cur = await loadSettings();
  const next = { ...cur, ...patch };
  const out = { name: next.name, relayUrl: next.relayUrl, lastMode: next.lastMode, alwaysOnTop: next.alwaysOnTop };
  // Code nur speichern, wenn das Betriebssystem ihn verschlüsseln kann.
  if (next.code && await safeStorage.isAsyncEncryptionAvailable()) {
    out.codeEnc = (await safeStorage.encryptStringAsync(next.code)).toString('base64');
  }
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(out), { mode: 0o600 });
}

// ---------- Fenster ----------
async function createWindow() {
  const s = await loadSettings();
  win = new BrowserWindow({
    width: 420,
    height: 620,
    minWidth: 320,
    minHeight: 420,
    title: 'Klassen-Status',
    backgroundColor: '#f4f7f2',
    alwaysOnTop: s.alwaysOnTop,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      devTools: !app.isPackaged,
    },
  });
  win.once('ready-to-show', () => win.show());
  win.loadURL(PAGE_URL);
  win.on('closed', () => { win = null; });
}

// Grundsätzlich alles Fremde blockieren.
app.on('web-contents-created', (_e, contents) => {
  contents.on('will-navigate', (e) => e.preventDefault());
  contents.on('will-redirect', (e) => e.preventDefault());
  contents.on('will-attach-webview', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
});

app.whenReady().then(() => {
  protocol.handle('app', (req) => {
    let u;
    try { u = new URL(req.url); } catch { return new Response('', { status: 400 }); }
    const type = RENDERER_FILES[u.pathname];
    if (u.host !== 'klasse' || !type) return new Response('', { status: 404 });
    const body = fs.readFileSync(path.join(__dirname, 'renderer', u.pathname.slice(1)));
    return new Response(body, {
      headers: { 'content-type': type, 'content-security-policy': CSP, 'x-content-type-options': 'nosniff' },
    });
  });
  if (app.isPackaged) Menu.setApplicationMenu(null);
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  // Keine Netzwerk-Anfragen aus der Oberfläche – nur app:// (die eigenen Dateien).
  session.defaultSession.webRequest.onBeforeRequest((details, cb) => {
    cb({ cancel: !details.url.startsWith('app://klasse/') && !details.url.startsWith('devtools://') });
  });
  createWindow();
});

app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.on('window-all-closed', () => { shutdown(); app.quit(); });
app.on('activate', () => { if (!win) createWindow(); });

function shutdown() {
  if (server) { server.stop(); server = null; }
  if (client) { client.stop(); client = null; }
  mode = null;
}

// ---------- Verbindung zur Oberfläche ----------
function send(ev, data) {
  if (win && !win.isDestroyed()) win.webContents.send('ev', { ev, data });
}

function notify(title, body) {
  if (!Notification.isSupported()) return;
  const n = new Notification({ title, body, silent: false });
  n.on('click', () => { if (win) { win.show(); win.focus(); } });
  n.show();
}

// Nur Nachrichten aus unserer eigenen Seite annehmen.
function trusted(event) {
  const url = event.senderFrame && event.senderFrame.url;
  try { return !!url && new URL(url).href.split('#')[0] === PAGE_URL; } catch { return false; }
}
function handle(channel, fn) {
  ipcMain.handle(channel, async (event, arg) => {
    if (!trusted(event)) throw new Error('nicht erlaubt');
    return fn(arg);
  });
}

handle('settings', async () => {
  const s = await loadSettings();
  return {
    name: s.name, relayUrl: s.relayUrl, lastMode: s.lastMode, alwaysOnTop: s.alwaysOnTop,
    code: s.code || '', defaultRelay: DEFAULT_RELAY_URL,
  };
});

handle('new-code', () => P.generateCode());

handle('start-admin', async (arg) => {
  if (!arg || typeof arg !== 'object') return { ok: false, error: 'Ungültig' };
  const name = P.cleanName(arg.name);
  const code = P.normalizeCode(arg.code) ? String(arg.code).toUpperCase().trim() : null;
  const relayUrl = P.cleanRelayUrl(arg.relayUrl);
  if (!name) return { ok: false, error: 'Bitte einen gültigen Namen eingeben (1–24 Zeichen, keine Sonderzeichen).' };
  if (!code) return { ok: false, error: 'Ungültiger Klassencode.' };
  if (!relayUrl) return { ok: false, error: 'Relay-Adresse muss mit wss:// beginnen.' };
  shutdown();
  const srv = new ClassServer({
    adminName: name, code, relayUrl,
    onRoster: (members, locked) => send('roster', { members: members.map((m) => ({ ...m, me: m.isAdmin })), locked }),
    onHelp: (who) => { notify('Frage', `${who} hat eine Frage`); send('help', who); },
    onConnState: (st) => send('state', st),
  });
  try {
    await srv.start();
  } catch (e) {
    srv.stop();
    return { ok: false, error: e.message };
  }
  server = srv;
  mode = 'admin';
  currentCode = code;
  await saveSettings({ name, code, relayUrl, lastMode: 'admin' });
  send('roster', { members: srv.roster().map((m) => ({ ...m, me: m.isAdmin })), locked: srv.locked });
  return { ok: true };
});

handle('join', async (arg) => {
  if (!arg || typeof arg !== 'object') return { ok: false, error: 'Ungültig' };
  const name = P.cleanName(arg.name);
  const code = P.normalizeCode(arg.code) ? String(arg.code).toUpperCase().trim() : null;
  const relayUrl = P.cleanRelayUrl(arg.relayUrl);
  if (!name) return { ok: false, error: 'Bitte einen gültigen Namen eingeben (1–24 Zeichen, keine Sonderzeichen).' };
  if (!code) return { ok: false, error: 'Der Klassencode hat 12 Zeichen, z.B. ABCD-EFGH-JKLM.' };
  if (!relayUrl) return { ok: false, error: 'Relay-Adresse muss mit wss:// beginnen.' };
  shutdown();
  const c = new ClassClient({ relayUrl, name, code });
  c.on('state', (st) => send('state', st));
  c.on('roster', (members, locked) => send('roster', { members, locked }));
  c.on('status', (st) => send('my-status', st));
  c.on('come', (from) => { notify('Kannst du kommen?', `${from} ruft dich.`); send('come', from); });
  c.on('rejected', (reason) => { send('ended', reason || 'Abgelehnt.'); shutdown(); });
  c.on('removed', () => { send('ended', 'Du wurdest vom Admin aus der Klasse entfernt.'); shutdown(); });
  c.on('wrong-code', () => { send('ended', 'Der Klassencode stimmt nicht.'); shutdown(); });
  client = c;
  mode = 'student';
  await saveSettings({ name, code, relayUrl, lastMode: 'student' });
  c.start();
  return { ok: true };
});

handle('set-status', (status) => {
  if (!P.isStatus(status)) return false;
  if (mode === 'admin' && server) server.setAdminStatus(status);
  else if (mode === 'student' && client) client.setStatus(status);
  return true;
});

const memberId = (id) => (typeof id === 'string' && id.length <= 64 ? id : null);
handle('call', (id) => (mode === 'admin' && server && memberId(id) ? server.callMember(id) : false));
handle('clear-question', (id) => { if (mode === 'admin' && server && memberId(id)) server.clearQuestion(id); return true; });
handle('remove', (id) => { if (mode === 'admin' && server && memberId(id)) server.removeMember(id); return true; });
handle('lock', (v) => { if (mode === 'admin' && server) server.setLocked(v === true); return true; });
handle('copy-code', () => { if (mode === 'admin' && currentCode) clipboard.writeText(currentCode); return true; });
handle('leave', () => { shutdown(); return true; });
handle('always-on-top', async (v) => {
  const on = v === true;
  if (win) win.setAlwaysOnTop(on);
  await saveSettings({ alwaysOnTop: on });
  return on;
});
