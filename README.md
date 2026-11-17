# Klassen-Status

> **Neu:** Eine Peer-to-Peer-Version in Python ohne Server liegt im Ordner [`p2p-python/`](p2p-python/).

Desktop-App für die Klasse (Windows, Mac, Linux). Alle sehen, wer gerade frei ist, und mit einem Klick auf **Hilfe** bekommt der Admin eine Meldung.

| Farbe | Bedeutung |
|---|---|
| 🟢 Grün | frei, Gespräch möglich |
| 🟠 Orange | hat eine Frage / braucht Hilfe |
| 🔴 Rot | im Call oder beschäftigt |
| ⚪ Grau | weg |

**Schüler:** sehen die ganze Klasse, stellen den eigenen Status ein („Ich“) und drücken **✋ Hilfe**, wenn sie eine Frage haben.
**Admin:** sieht „Meine Gruppe“, bekommt eine Meldung „… hat eine Frage“, kann jemanden mit **Kannst du kommen?** rufen, Fragen als erledigt markieren, Leute entfernen und die Klasse **schliessen** (dann kommen keine Neuen mehr rein).

Es funktioniert übers Internet, also auch mit Handy-Hotspot, nicht nur im gleichen WLAN.

---

## Einrichten (einmalig)

### 1. Relay-Server starten (gratis)

Der Relay leitet nur verschlüsselte Nachrichten weiter. Er kennt den Klassencode nicht und kann nichts mitlesen.

1. Auf <https://render.com> mit GitHub anmelden.
2. **New → Blueprint** wählen und dieses Repository auswählen. Render liest `render.yaml` und richtet alles ein.
3. Nach ein paar Minuten steht oben eine Adresse, z.B. `https://klassen-status-relay.onrender.com`.
4. In `src/config.js` diese Adresse eintragen, aber mit **`wss://`** statt `https://`:
   ```js
   DEFAULT_RELAY_URL: 'wss://klassen-status-relay.onrender.com',
   ```
   Committen und pushen.

> Der Gratis-Plan schläft nach ca. 15 Minuten ohne Benutzung ein. Beim ersten Verbinden kann es dann bis zu einer Minute dauern, die App versucht es automatisch weiter.

### 2. App bauen

Auf GitHub: **Actions → App bauen → Run workflow**. Nach ca. 10 Minuten unten bei „Artifacts“ herunterladen:

- **Windows:** `Klassen-Status-…-win-x64.exe` (Installer) oder die portable Version
- **Mac:** `…-mac-arm64.dmg` (M1/M2/M3/M4) oder `…-mac-x64.dmg` (Intel)
- **Linux:** `.AppImage` (überall) oder `.deb` (Ubuntu/Debian)

Mit einem Tag (z.B. `git tag v1.0.0 && git push --tags`) wird zusätzlich ein Release mit allen Dateien erstellt.

### 3. Installieren

Die App ist nicht mit einem gekauften Zertifikat signiert, deshalb warnt das System beim ersten Start:

- **Windows:** „Der Computer wurde durch Windows geschützt“ → **Weitere Informationen → Trotzdem ausführen**.
- **Mac:** App in „Programme“ ziehen, dann **Rechtsklick → Öffnen → Öffnen**. Falls „beschädigt“ erscheint, im Terminal: `xattr -cr /Applications/Klassen-Status.app`
- **Linux:** `chmod +x Klassen-Status-*.AppImage` und starten.

---

## Benutzen

1. **Admin** öffnet die App → Tab **Admin** → Name eingeben → **Klasse starten**. Der Klassencode (z.B. `K7QM-3XPA-W9TD`) wird angezeigt. Mit „kopieren“ kann man ihn verschicken.
2. **Schüler** → Tab **Beitreten** → Name und Klassencode → **Beitreten**.
3. Name und Code werden gespeichert, beim nächsten Mal nur noch auf den Knopf drücken.

Die Admin-App muss offen sein, damit die Klasse funktioniert. Ist sie zu, zeigen die Schüler-Apps „Admin nicht online“ und verbinden sich automatisch, sobald sie wieder da ist.

📌 = Fenster bleibt immer im Vordergrund.

---

## Sicherheit

- **Ende-zu-Ende verschlüsselt:** Jede Nachricht ist mit AES-256-GCM verschlüsselt. Der Schlüssel kommt aus dem Klassencode (scrypt). Ohne Code kann niemand mitlesen, Nachrichten fälschen, wiederholen oder umsortieren, auch nicht der Relay-Server.
- **Verbindung** zum Relay läuft nur über `wss://` (TLS).
- **Admin-Rechte** gibt es nur in der Admin-App selbst. Schüler-Apps können nur ihren eigenen Status ändern.
- **Electron abgesichert:** Sandbox, Context Isolation, kein Node in der Oberfläche, strenge Content-Security-Policy, keine externen Seiten oder Links, alle Berechtigungen (Kamera, Mikro …) gesperrt, Electron-Fuses (kein `RunAsNode`, ASAR-Integritätsprüfung).
- **Eingaben geprüft:** Namen nur Buchstaben/Zahlen (max. 24 Zeichen), alles wird als Text angezeigt (kein HTML).
- **Gegen Spam:** Nachrichten-Limits, maximale Grösse, max. 100 Personen pro Klasse.
- Der Klassencode wird mit der Schlüsselverwaltung des Betriebssystems verschlüsselt gespeichert.
- **Dependabot** meldet automatisch, wenn Pakete Sicherheits-Updates brauchen.

Grenzen, die man kennen sollte: Wer den Klassencode hat, gehört zur Klasse und könnte sich unter dem Namen von jemandem eintragen, der gerade offline ist. Wenn der Code in falsche Hände gerät: im Admin-Tab auf **Neu** klicken und den neuen Code verteilen.

---

## Für Entwickler

```bash
npm install
npm test            # Tests für Verschlüsselung, Relay und Ablauf
npm run relay       # Relay lokal auf Port 8080
npm start           # App starten (für lokal unter Erweitert: ws://localhost:8080)
npm run dist        # App für das eigene System bauen
```

Aufbau:

- `main.js`: Electron-Hauptprozess, Fenster, Sicherheit, Speicher
- `preload.js`: die einzige Brücke zur Oberfläche
- `renderer/`: Oberfläche (HTML/CSS/JS)
- `src/protocol.js`: Verschlüsselung und Prüfungen
- `src/server.js`: Logik der Klasse (läuft in der Admin-App)
- `src/client.js`: Schüler-Verbindung
- `relay/`: Relay-Server für Render.com
