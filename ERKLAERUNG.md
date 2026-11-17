# Klassenzimmer – einfach erklärt

Diese Seite ist zum **Weitererklären** gedacht, zum Beispiel für die Klasse, den Coach oder eine Präsentation. Sie hat drei Teile: was die App kann, wie man sie benutzt und wie sie funktioniert.

---

## 1. Was ist das?

Eine App, die im Klassenzimmer zeigt:
- **wer da ist** und ob man gerade gestört werden darf
- **wer Hilfe braucht**, in der richtigen Reihenfolge

Das Besondere: Es gibt **keinen Server** und kein Konto. Die Apps reden direkt miteinander über das WLAN. Man nennt das **Peer-to-Peer** („von Gleich zu Gleich“).

---

## 2. Alle Funktionen

### Für alle

| Funktion | Was passiert |
|---|---|
| **Teilnehmerliste** | Alle aus der eigenen Klasse, jeweils mit farbigem Punkt |
| 🟢 **Online** | Die Person ist da und darf angesprochen werden |
| 🟡 **Nicht stören** | Die Person ist da, will aber gerade nicht gestört werden |
| ⚪ **Offline** | Die App ist zu, oder seit 10 Sekunden kam kein Lebenszeichen |
| **Status wechseln** | Oben rechts auf den Knopf klicken: grün ↔ gelb. Die anderen sehen das nach weniger als einer Sekunde |
| **Klasse wird gespeichert** | Wer einmal gesehen wurde, steht am nächsten Tag schon grau in der Liste und wird grün, sobald er die App startet |
| **Aus Liste entfernen** | Bei grauen Namen auf ✕ klicken, z.B. wenn jemand die Klasse verlassen hat |
| **Mehrere Klassen** | Nur wer denselben Klassennamen hat, sieht sich, auch im selben WLAN |
| **Autostart** | Startet beim Anmelden am Computer automatisch, ohne Fragen |
| **Nur einmal offen** | Ein zweiter Start meldet „Die App läuft schon“ |

### Für Schüler

| Funktion | Was passiert |
|---|---|
| **„Coach um Hilfe fragen“** | Schickt eine Anfrage an alle Coaches, die online sind. Optional mit kurzem Text, z.B. „Aufgabe 3b“ |
| **Bestätigung** | Unter dem Knopf steht: *wird gesendet … (Versuch 2/5)* → **✓ angekommen** → **✓ erledigt** |
| **Fehlermeldung** | *Kein Coach online* oder *✗ nicht angekommen*, wenn es nach 5 Versuchen nicht geklappt hat |
| **Nochmal fragen** | Ergänzt die bestehende Anfrage und stellt sich **nicht** nochmal hinten an |

### Für den Coach

| Funktion | Was passiert |
|---|---|
| **Warteschlange** | Alle Anfragen mit Uhrzeit, Name und Text, die **älteste zuerst** |
| **Ton** | Bei einer neuen Anfrage gibt es einen kurzen Ton |
| **„Erledigt“** | Entfernt die Anfrage. Der Schüler sieht „✓ erledigt“ |

---

## 3. Wie benutzt man sie?

**Einmalig:**
1. App herunterladen (Releases auf GitHub) und starten.
2. Im Startfenster **Name**, **Klasse** (z.B. `INF3a`, bei allen gleich!) und **Rolle** eingeben.
3. Das Häkchen **„Beim Anmelden automatisch starten“** setzen.
4. Beim ersten Start die Frage der Firewall bzw. „Lokales Netzwerk“ mit **Zulassen** beantworten.

**Jeden Tag:** nichts tun. Die App startet beim Anmelden von selbst, und die Klasse ist schon da.

**Ändern** (anderer Name oder andere Klasse): App schliessen, normal neu starten, im Startfenster ändern.

---

## 4. Wie funktioniert das? (einfach erklärt)

### Wie finden sich die Computer? → „In den Raum rufen“

Alle 5 Sekunden ruft jede App ins WLAN: **„Ich bin Lena, Klasse INF3a, Status grün!“** Das nennt man **Broadcast**: eine Nachricht an alle im Netz, auf Port 50505. Alle anderen hören das und tragen Lena in ihre Liste ein. Weil das regelmässig passiert, heisst so eine Nachricht **Heartbeat** (Herzschlag).

### Wie merkt man, dass jemand weg ist? → „Kein Herzschlag mehr“

Hört man 10 Sekunden lang nichts von jemandem, also zwei Heartbeats verpasst, wird der Punkt **grau**. Wer die App normal schliesst, ruft vorher noch **„Tschüss!“** (`bye`). Dann wird er sofort grau.

### Wie kommt die Hilfeanfrage sicher an? → „Einschreiben mit Rückschein“

Ein Broadcast ist wie eine Durchsage: Man weiss nicht, ob es jeder gehört hat. Bei einer Hilfeanfrage soll aber nichts verloren gehen. Darum:

1. Die Anfrage geht **direkt** an den Computer des Coaches und nicht an alle.
2. Die App des Coaches antwortet: **„Angekommen!“** Das nennt man ein **ACK** (Bestätigung).
3. Kommt nach 3 Sekunden kein ACK, schickt die App die Anfrage **nochmal**, höchstens 5 Mal.

```
Schüler                              Coach
   │ ── Hilfe! (Nr. 42) ─────X          (verloren)
   │    … 3 Sekunden nichts …
   │ ── Hilfe! (Nr. 42) ───────────────▶ ✓ in die Warteschlange
   │ ◀──────────────── Angekommen 42 ── │
   ✓ angekommen
```

### Was, wenn eine Anfrage doppelt ankommt? → „Jede Nachricht hat eine Nummer“

Geht nur das „Angekommen“ verloren, schickt der Schüler nochmal, und der Coach bekommt die Anfrage zweimal. Jede Nachricht hat aber eine **eindeutige Nummer** (ID). Der Coach merkt sich die Nummern. Bei einer bekannten Nummer zeigt er die Anfrage **nicht nochmal** an, sagt aber **nochmal „Angekommen“**, damit der Schüler aufhören kann zu senden.

### Warum friert das Fenster nie ein? → „Zwei Arbeiter mit Briefkasten“

Im Programm arbeiten mehrere **Threads** gleichzeitig:
- Die **Netzwerk-Threads** warten auf Nachrichten und senden Heartbeats.
- Der **Hauptthread** kümmert sich nur um das Fenster.

Die Netzwerk-Threads legen alles, was passiert, in einen **Briefkasten** (eine Queue). Das Fenster leert ihn alle 0,1 Sekunden. Das Fenster wartet also nie auf das Netzwerk und bleibt immer flüssig.

### Wie merkt sich die App die Klasse? → „Ein Notizbuch auf dem Computer“

Jede App speichert in einer kleinen Datei: den eigenen Namen, die Klasse, eine **feste ID** und alle Mitschüler, die sie schon gesehen hat. Am nächsten Morgen liest sie diese Datei und zeigt alle sofort an, zuerst grau. Die feste ID sorgt dafür, dass Lena morgen wieder als *dieselbe* Lena erkannt wird und nicht als neue Person.

Gespeichert wird hier:
- Windows: `%APPDATA%\klassenzimmer\`
- Mac: `~/Library/Application Support/klassenzimmer/`
- Linux: `~/.config/klassenzimmer/`

---

## 5. Gut zu wissen (Grenzen)

- **Nur im selben Netz:** Alle müssen im selben WLAN/LAN sein. Verschiedene Hotspots gehen nicht.
- **Manche WLANs blockieren das:** Viele Schul- und Gäste-WLANs haben „Client Isolation“. Dann dürfen Geräte nicht direkt miteinander reden, und die App findet niemanden. Lösung: anderes WLAN oder ein eigener Router.
- **Firewall:** Beim ersten Start muss man den Netzwerkzugriff erlauben. Unter Linux mit ufw: `sudo ufw allow 50505:50506/udp` und die App mit `--port 50506` starten.
- **Nicht verschlüsselt:** Wer im selben WLAN ist, könnte mitlesen oder sich als jemand anderes ausgeben. Darum keine privaten Dinge in die Hilfeanfrage schreiben.
- **Die Warteschlange ist nicht gespeichert:** Schliesst der Coach die App, sind offene Anfragen weg.
- **Warnung beim ersten Start:** Windows und Mac warnen, weil die App nicht kostenpflichtig signiert ist. Das ist normal.

---

## 6. In einem Satz

> Jede App ruft alle 5 Sekunden „Ich bin da“ ins WLAN, merkt sich, wen sie hört, und schickt Hilfeanfragen direkt an den Coach – so lange, bis der „Angekommen“ zurückruft.
