'use strict';
// Einzige Brücke zwischen Oberfläche und App. Nur diese Funktionen sind erlaubt.
const { contextBridge, ipcRenderer } = require('electron');

const call = (ch) => (arg) => ipcRenderer.invoke(ch, arg);

contextBridge.exposeInMainWorld('klasse', {
  settings: call('settings'),
  newCode: call('new-code'),
  startAdmin: call('start-admin'),
  join: call('join'),
  setStatus: call('set-status'),
  call: call('call'),
  clearQuestion: call('clear-question'),
  remove: call('remove'),
  lock: call('lock'),
  copyCode: call('copy-code'),
  leave: call('leave'),
  alwaysOnTop: call('always-on-top'),
  onEvent: (fn) => {
    const h = (_e, msg) => fn(msg);
    ipcRenderer.on('ev', h);
    return () => ipcRenderer.removeListener('ev', h);
  },
});
