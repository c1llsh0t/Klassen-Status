'use strict';
// Oberfläche. Kein innerHTML: alle Texte werden mit textContent gesetzt,
// damit niemand über seinen Namen Code einschleusen kann.

const api = window.klasse;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const LABEL = { frei: 'frei', beschaeftigt: 'beschäftigt', frage: 'hat eine Frage', weg: 'weg' };

let mode = 'student';
let myStatus = 'frei';
let statusBeforeHelp = 'frei';
let defaultRelay = '';
let pinned = false;

// ---------- Start ----------
async function init() {
  const s = await api.settings();
  defaultRelay = s.defaultRelay;
  $('in-name').value = s.name;
  $('in-relay').value = s.relayUrl;
  pinned = s.alwaysOnTop;
  $('btn-pin').classList.toggle('on', pinned);
  setTab(s.lastMode);
  if (s.code) $('in-code').value = s.code;
  if (s.lastMode === 'admin' && !s.code) $('in-code').value = await api.newCode();
}

function setTab(m) {
  mode = m;
  $('tab-join').classList.toggle('active', m === 'student');
  $('tab-admin').classList.toggle('active', m === 'admin');
  $('btn-go').textContent = m === 'admin' ? 'Klasse starten' : 'Beitreten';
  $('btn-newcode').classList.toggle('hidden', m !== 'admin');
  $('admin-hint').classList.toggle('hidden', m !== 'admin');
  $('err').textContent = '';
}

$('tab-join').addEventListener('click', () => setTab('student'));
$('tab-admin').addEventListener('click', async () => {
  setTab('admin');
  if (!$('in-code').value.trim()) $('in-code').value = await api.newCode();
});
$('btn-newcode').addEventListener('click', async () => { $('in-code').value = await api.newCode(); });

$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('btn-go');
  btn.disabled = true;
  $('err').textContent = mode === 'admin' ? 'Verbinde…' : '';
  const arg = {
    name: $('in-name').value,
    code: $('in-code').value,
    relayUrl: $('in-relay').value.trim() || defaultRelay,
  };
  const res = mode === 'admin' ? await api.startAdmin(arg) : await api.join(arg);
  btn.disabled = false;
  if (!res.ok) { $('err').textContent = res.error; return; }
  $('err').textContent = '';
  enterMain(arg.code);
});

function enterMain(code) {
  myStatus = 'frei';
  $('setup').classList.add('hidden');
  $('main').classList.remove('hidden');
  $('list-title').textContent = mode === 'admin' ? 'Meine Gruppe' : 'Klasse';
  $('adminbar').classList.toggle('hidden', mode !== 'admin');
  $('btn-help').classList.toggle('hidden', mode === 'admin');
  $('code-text').textContent = code.toUpperCase().trim();
  $('banners').replaceChildren();
  $('list').replaceChildren();
  renderMe();
}

function backToSetup(message) {
  $('main').classList.add('hidden');
  $('setup').classList.remove('hidden');
  $('err').textContent = message || '';
}

// ---------- Hauptansicht ----------
$('btn-leave').addEventListener('click', async () => { await api.leave(); backToSetup(''); });
$('btn-legend').addEventListener('click', () => {
  $('legend').classList.toggle('hidden');
  $('btn-legend').classList.toggle('on');
});
$('btn-pin').addEventListener('click', async () => {
  pinned = await api.alwaysOnTop(!pinned);
  $('btn-pin').classList.toggle('on', pinned);
});
$('btn-copy').addEventListener('click', async () => {
  await api.copyCode();
  banner('info', 'Code kopiert.', 2000);
});

let locked = false;
$('btn-lock').addEventListener('click', () => api.lock(!locked));

for (const b of document.querySelectorAll('.sb')) {
  b.addEventListener('click', () => setMyStatus(b.dataset.s));
}
$('btn-help').addEventListener('click', () => {
  if (myStatus === 'frage') setMyStatus(statusBeforeHelp === 'frage' ? 'frei' : statusBeforeHelp);
  else { statusBeforeHelp = myStatus; setMyStatus('frage'); }
});

function setMyStatus(s) {
  myStatus = s;
  api.setStatus(s);
  renderMe();
}

function renderMe() {
  $('my-dot').className = 'd ' + myStatus;
  $('my-dot').title = LABEL[myStatus];
  for (const b of document.querySelectorAll('.sb')) b.classList.toggle('active', b.dataset.s === myStatus);
  const h = $('btn-help');
  h.classList.toggle('active', myStatus === 'frage');
  h.textContent = myStatus === 'frage' ? 'Frage zurückziehen' : '✋ Hilfe';
}

function banner(kind, text, ttl, withOk) {
  const b = el('div', 'banner ' + kind);
  b.append(el('span', null, text));
  if (withOk) {
    const ok = el('button', null, 'OK');
    ok.addEventListener('click', () => b.remove());
    b.append(ok);
  }
  $('banners').prepend(b);
  while ($('banners').children.length > 4) $('banners').lastChild.remove();
  if (ttl) setTimeout(() => b.remove(), ttl);
}

const ORDER = { frage: 0, frei: 1, beschaeftigt: 2, weg: 3 };
function renderRoster(members) {
  const others = members.filter((m) => !m.me);
  others.sort((a, b) => {
    if (a.isAdmin !== b.isAdmin) return a.isAdmin ? -1 : 1;
    if (mode === 'admin' && ORDER[a.status] !== ORDER[b.status]) return ORDER[a.status] - ORDER[b.status];
    return a.name.localeCompare(b.name, 'de');
  });

  const items = others.map((m) => {
    const li = el('li', (m.status === 'frage' ? 'frage ' : '') + (m.online ? '' : 'offline'));
    const dot = el('span', 'd ' + m.status);
    dot.title = LABEL[m.status];
    const name = el('span', 'name', m.name);
    if (m.isAdmin) name.append(el('small', null, 'Admin'));
    else if (m.status === 'frage' && mode !== 'admin') name.append(el('small', null, 'hat eine Frage'));
    li.append(dot, name);

    if (mode === 'admin' && !m.isAdmin) {
      if (m.status === 'frage') {
        const done = el('button', 'pill done', 'Erledigt');
        done.title = 'Frage als erledigt markieren';
        done.addEventListener('click', () => api.clearQuestion(m.id));
        li.append(done);
      }
      if (m.online) {
        const come = el('button', 'pill', 'Kannst du kommen?');
        come.addEventListener('click', async () => {
          if (await api.call(m.id)) banner('info', `${m.name} wurde gerufen.`, 2500);
        });
        li.append(come);
      }
      const x = el('button', 'x', '✕');
      x.title = 'Aus der Klasse entfernen';
      x.addEventListener('click', () => {
        if (confirm(`${m.name} aus der Klasse entfernen?`)) api.remove(m.id);
      });
      li.append(x);
    }
    return li;
  });
  $('list').replaceChildren(...items);
  $('empty').classList.toggle('hidden', others.length > 0);

  const me = members.find((m) => m.me);
  if (me && me.status !== myStatus) { myStatus = me.status; renderMe(); }
}

const STATE_TEXT = {
  verbinde: ['verbinde…', ''],
  online: ['verbunden', 'online'],
  getrennt: ['Verbindung weg – versuche erneut…', 'bad'],
  'kein-admin': ['Admin nicht online (oder Code falsch) – warte…', 'bad'],
  doppelt: ['Code ist schon auf einem anderen PC aktiv', 'bad'],
};

api.onEvent(({ ev, data }) => {
  switch (ev) {
    case 'state': {
      const [t, c] = STATE_TEXT[data] || [String(data), ''];
      $('conn').textContent = t;
      $('conn').className = 'conn ' + c;
      break;
    }
    case 'roster':
      locked = !!data.locked;
      $('btn-lock').textContent = locked ? '🔒 Geschlossen' : '🔓 Offen';
      $('btn-lock').classList.toggle('closed', locked);
      renderRoster(data.members);
      break;
    case 'my-status':
      myStatus = data;
      renderMe();
      if (data !== 'frage') banner('info', 'Deine Frage wurde als erledigt markiert.', 4000);
      break;
    case 'help':
      banner('help', `${data} hat eine Frage`, 15000, true);
      break;
    case 'come':
      banner('come', `${data}: Kannst du kommen?`, 0, true);
      break;
    case 'ended':
      backToSetup(data);
      break;
    default:
  }
});

init();
