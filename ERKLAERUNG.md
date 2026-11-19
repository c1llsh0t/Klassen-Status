# Klassenzimmer – einfach erklärt

Diese Seite ist zum **Weitererklären** gedacht, zum Beispiel für die Klasse, den Coach oder eine Präsentation. Sie hat drei Teile: was die App kann, wie man sie benutzt und wie sie funktioniert.

---

## 1. Was ist das?

Eine App, die im Klassenzimmer zeigt:
- **wer da ist** und ob man gerade gestört werden darf
- **wer Hilfe braucht**, in der richtigen Reihenfolge

Das Besondere: Es gibt **keinen eigenen Server** und kein Konto. Die Apps reden direkt miteinander über das WLAN. Man nennt das **Peer-to-Peer** („von Gleich zu Gleich“). Lässt das WLAN das nicht zu, gehen die Nachrichten ab Version 2.3 verschlüsselt über einen öffentlichen Vermittler im Internet.

---

## 2. Alle Funktionen

### Für alle

| Funktion | Was passiert |
|---|---|
| **Beitrittscode** | Der Coach erzeugt einen Code (z.B. `K7Q-M3X`), die Schüler tippen ihn ein. Nur wer den Code kennt, ist in der Klasse |
| **Klein statt gross** | Windows, Mac, Linux: eine kleine Leiste am Bildschirmrand, die immer sichtbar ist. Omarchy: ein farbiger Punkt oben in der Waybar. Das grosse Fenster öffnet sich nur, wenn man es braucht |
| **Teilnehmerliste** | Alle aus der eigenen Klasse, jeweils mit farbigem Punkt |
| 🟢 **Online** | Die Person ist da und darf angesprochen werden |
| 🟡 **Nicht stören** | Die Person ist da, will aber gerade nicht gestört werden |
| ⚪ **Offline** | Die App ist zu, oder seit 20 Sekunden kam kein Lebenszeichen |
| **Status wechseln** | Auf den Punkt in der Leiste klicken (Waybar: Rechtsklick): grün ↔ gelb. Die anderen sehen das nach weniger als einer Sekunde |
| **Klasse wird gespeichert** | Wer einmal gesehen wurde, steht am nächsten Tag schon grau in der Liste und wird grün, sobald er die App startet |
| **Aus Liste entfernen** | Bei grauen Namen auf ✕ klicken, z.B. wenn jemand die Klasse verlassen hat |
| **Mehrere Klassen** | Nur wer denselben Code hat, sieht sich, auch im selben WLAN |
| **Autostart** | Startet beim Anmelden am Computer automatisch, ohne Fragen |
| **Nur einmal offen** | Ein zweiter Start öffnet einfach das Fenster der laufenden App |

### Für Schüler

| Funktion | Was passiert |
|---|---|
| **✋ in der Leiste** | Schnell um Hilfe fragen, ohne Text. Danach zeigt die Leiste `…`, dann `✓` (angekommen) |
| **„Coach um Hilfe fragen“** (grosses Fenster) | Schickt eine Anfrage an alle Coaches, die online sind. Optional mit kurzem Text, z.B. „Aufgabe 3b“ |
| **Bestätigung** | Unter dem Knopf steht: *wird gesendet … (Versuch 2/5)* → **✓ angekommen** → **✓ erledigt** |
| **Fehlermeldung** | *Kein Coach online* oder *✗ nicht angekommen*, wenn es nach 5 Versuchen nicht geklappt hat |
| **Nochmal fragen** | Ergänzt die bestehende Anfrage und stellt sich **nicht** nochmal hinten an |

### Für den Coach

| Funktion | Was passiert |
|---|---|
| **Code erzeugen** | Beim ersten Start „Coach“ wählen, dann zeigt die App einen Code. Er steht auch oben im Fenster, ein Klick kopiert ihn |
| **🔔 in Leiste/Waybar** | Zeigt, wie viele Fragen offen sind, z.B. 🔔 2 |
| **Warteschlange** | Alle Anfragen mit Uhrzeit, Name und Text, die **älteste zuerst** |
| **Ton** | Bei einer neuen Anfrage gibt es einen kurzen Ton |
| **„Erledigt“** | Entfernt die Anfrage. Der Schüler sieht „✓ erledigt“ |

---

## 3. Wie benutzt man sie?

**Einmalig (Coach):**
1. App herunterladen (Releases auf GitHub) und starten.
2. Name eingeben, **Coach** wählen und den Klassennamen eintragen. Den angezeigten **Code** an die Tafel schreiben.
3. Häkchen **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

**Einmalig (Schüler):**
1. App herunterladen und starten.
2. Name eingeben, **Schüler/in** wählen und den **Code von der Tafel** eintippen.
3. Häkchen **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

Beim ersten Start die Frage der Firewall bzw. „Lokales Netzwerk“ mit **Zulassen** beantworten. Wer zu faul ist: Auf der GitHub-Startseite steht ein Text für Claude, der alles installiert.

**Jeden Tag:** nichts tun. Die App startet beim Anmelden von selbst als kleine Leiste bzw. als Punkt in der Waybar, und die Klasse ist schon da.

**Ändern** (anderer Name oder anderer Code): App beenden (⏻ oder Rechtsklick → Beenden), normal neu starten, im Startfenster ändern.

---

## 4. Wie funktioniert das? (einfach erklärt)

### Wie finden sich die Computer? → „In den Raum rufen“

Alle 5 Sekunden ruft jede App ins WLAN: **„Ich bin Lena, Status grün!“** Das nennt man **Broadcast**: eine Nachricht an alle im Netz, auf Port 50505. Alle anderen hören das und tragen Lena in ihre Liste ein. Weil das regelmässig passiert, heisst so eine Nachricht **Heartbeat** (Herzschlag).

### Wie bleibt die Klasse unter sich? → „Ein Stempel, den nur die Klasse hat“

Aus dem Beitrittscode macht jede App einen geheimen **Stempel**. Jede Nachricht bekommt diesen Stempel, das heisst **Signatur**. Wer den Code nicht kennt, kann den Stempel nicht nachmachen. Seine Nachrichten werden einfach ignoriert. So stören sich zwei Klassen im selben WLAN nicht, und niemand von aussen kann sich als Coach ausgeben oder gefälschte Hilfeanfragen schicken. Ausserdem steht in jeder Nachricht die Uhrzeit, damit niemand eine alte, aufgezeichnete Nachricht nochmal abspielen kann.

Wichtig: Der Stempel macht die Nachricht nicht unlesbar. Wer im WLAN mithört, kann den Inhalt trotzdem lesen.

### Wie merkt man, dass jemand weg ist? → „Kein Herzschlag mehr“

Hört man 20 Sekunden lang nichts von jemandem, also vier Heartbeats hintereinander verpasst, wird der Punkt **grau**. Wer die App normal schliesst, ruft vorher noch **„Tschüss!“** (`bye`). Dann wird er sofort grau.

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

Jede App speichert in einer kleinen Datei: den eigenen Namen, den Code, eine **feste ID** und alle Mitschüler, die sie schon gesehen hat. Am nächsten Morgen liest sie diese Datei und zeigt alle sofort an, zuerst grau. Die feste ID sorgt dafür, dass Lena morgen wieder als *dieselbe* Lena erkannt wird und nicht als neue Person.

Gespeichert wird hier:
- Windows: `%APPDATA%\klassenzimmer\`
- Mac: `~/Library/Application Support/klassenzimmer/`
- Linux: `~/.config/klassenzimmer/`

---

## 5. Gut zu wissen (Grenzen)

- **Manche WLANs blockieren das:** Viele Schul- und Gäste-WLANs haben „Client Isolation“. Dann dürfen Geräte nicht direkt miteinander reden. Ab Version 2.3 geht die App dann übers Internet. Das braucht den öffentlichen Vermittler `public.cloud.shiftr.io`. Ist der einmal nicht erreichbar, findet man sich nur im selben WLAN.
- **Firewall:** Beim ersten Start muss man den Netzwerkzugriff erlauben. Unter Linux mit ufw: `sudo ufw allow 50505:50506/udp`. Details stehen in der README.
- **Im WLAN nicht verschlüsselt:** Übers Internet ist alles mit dem Code verschlüsselt. Im WLAN selbst kann aber mitlesen, wer im selben WLAN ist (fälschen kann er ohne Code nichts). Wer den Code kennt (die Klasse), könnte sich theoretisch als jemand anderes ausgeben. Darum keine privaten Dinge in die Hilfeanfrage schreiben.
- **Uhrzeit:** Geht die Uhr eines Computers mehr als 10 Minuten falsch, kann er nicht mitmachen.
- **Die Warteschlange ist nicht gespeichert:** Schliesst der Coach die App, sind offene Anfragen weg.
- **Warnung beim ersten Start:** Windows und Mac warnen, weil die App nicht kostenpflichtig signiert ist. Das ist normal.

---

## 6. In einem Satz

> Jede App ruft alle 5 Sekunden „Ich bin da“ ins WLAN, merkt sich, wen sie hört, und schickt Hilfeanfragen direkt an den Coach – so lange, bis der „Angekommen“ zurückruft.
