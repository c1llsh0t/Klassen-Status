'use strict';
// Simulierte Schüler für den Oberflächen-Test.
const { ClassClient } = require('../src/client');
const [relayUrl, code] = process.argv.slice(2);
const bots = [['Tim', 'beschaeftigt'], ['Noah', 'frage'], ['Mia', 'frei'], ['Jonas', 'frei'], ['Elif', 'weg']];
for (const [name, st] of bots) {
  const c = new ClassClient({ relayUrl, name, code });
  c.on('state', (s) => { if (s === 'online') setTimeout(() => c.setStatus(st), 300); });
  c.start();
}
setTimeout(() => process.exit(0), 25000);
