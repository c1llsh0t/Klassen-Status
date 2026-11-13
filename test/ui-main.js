'use strict';
// Nur für Tests: startet die App mit eigenem Datenordner und steuert die Oberfläche.
const { app } = require('electron');
const path = require('path');
const fs = require('fs');
app.setPath('userData', process.env.KS_USER_DATA);
require('../main.js');

const steps = JSON.parse(process.env.KS_STEPS || '[]');
app.on('browser-window-created', (_e, win) => {
  win.webContents.once('did-finish-load', async () => {
    for (const s of steps) {
      if (s.wait) await new Promise((r) => setTimeout(r, s.wait));
      if (s.js) {
        try { await win.webContents.executeJavaScript(s.js); } catch (e) { console.error('JS-Fehler', e.message); }
      }
      if (s.shot) {
        const img = await win.webContents.capturePage();
        fs.writeFileSync(path.resolve(s.shot), img.toPNG());
        console.log('Bild', s.shot);
      }
    }
    if (process.env.KS_QUIT) app.quit();
  });
});
