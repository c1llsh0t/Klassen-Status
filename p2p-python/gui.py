"""
SCHRITT 4: Die Oberfläche (tkinter)

Goldene Regel: Nur der Hauptthread darf tkinter-Widgets anfassen.

Darum holt die Oberfläche alle 100 ms die Ereignisse aus der Queue
(Methode _poll) und reagiert darauf. Dazu läuft jede Sekunde _tick, das
prüft, wer sich zu lange nicht gemeldet hat (-> grau/offline).

Die Oberfläche hält den ganzen "Zustand":
  self.peers     – wer ist da? (peer_id -> Infos + wann zuletzt gehört)
  self.queue     – Hilfeanfragen beim Coach (älteste zuerst)
  self.requests  – meine gesendeten Anfragen als Schüler (Status je Coach)
"""

import queue
import time
import tkinter as tk
from tkinter import ttk

import protocol as P

COLORS = {"online": "#2e9e44", "busy": "#e0b000", "offline": "#9a9a9a"}
STATUS_TEXT = {"online": "Online", "busy": "Nicht stören", "offline": "Offline"}
ROLE_TEXT = {"student": "Schüler/in", "coach": "Coach"}


def dot(parent, color, size=14):
    """Ein farbiger Punkt (ein Kreis auf einem kleinen Canvas)."""
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=parent["bg"])
    c.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
    return c


class App:
    def __init__(self, root, me, net, events):
        self.root = root
        self.me = me
        self.net = net
        self.events = events

        self.peers = {}      # peer_id -> {name, role, status, ip, port, last_seen}
        self.queue = []      # Coach: [{help_id, name, text, ip, port, time}]
        self.requests = {}   # Schüler: help_id -> {coach, state, tries}

        root.title("Klassenzimmer – %s" % me["name"])
        root.geometry("420x560")
        root.minsize(360, 420)
        root.configure(bg="white")
        self._build()

        root.protocol("WM_DELETE_WINDOW", self.quit)  # Fenster-X -> bye senden
        root.after(100, self._poll)
        root.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Aufbau der Oberfläche
    # ------------------------------------------------------------------
    def _build(self):
        bg = "white"

        # --- Oben: ich selbst + Status-Knopf ---
        top = tk.Frame(self.root, bg=bg, padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="%s (%s)" % (self.me["name"], ROLE_TEXT[self.me["role"]]),
                 font=("TkDefaultFont", 12, "bold"), bg=bg).pack(side="left")
        self.status_btn = tk.Button(top, command=self.toggle_status, relief="groove",
                                    padx=10, cursor="hand2")
        self.status_btn.pack(side="right")
        self._update_status_button()

        ttk.Separator(self.root).pack(fill="x")

        # --- Mitte: Teilnehmerliste ---
        tk.Label(self.root, text="Teilnehmer", bg=bg, anchor="w",
                 font=("TkDefaultFont", 10, "bold"), padx=12, pady=6).pack(fill="x")
        self.peer_frame = tk.Frame(self.root, bg=bg, padx=12)
        self.peer_frame.pack(fill="both", expand=True)

        ttk.Separator(self.root).pack(fill="x")

        # --- Unten: je nach Rolle ---
        bottom = tk.Frame(self.root, bg=bg, padx=12, pady=10)
        bottom.pack(fill="x")
        if self.me["role"] == "student":
            self._build_student(bottom)
        else:
            self._build_coach(bottom)

        self._render_peers()

    def _build_student(self, parent):
        bg = parent["bg"]
        tk.Label(parent, text="Frage (optional):", bg=bg, anchor="w").pack(fill="x")
        self.help_text = tk.Entry(parent)
        self.help_text.pack(fill="x", pady=(2, 6))
        self.help_text.bind("<Return>", lambda e: self.ask_for_help())
        tk.Button(parent, text="Coach um Hilfe fragen", command=self.ask_for_help,
                  bg="#ff9f1a", fg="white", activebackground="#e88a00",
                  font=("TkDefaultFont", 11, "bold"), cursor="hand2").pack(fill="x")
        self.request_frame = tk.Frame(parent, bg=bg, pady=6)
        self.request_frame.pack(fill="x")

    def _build_coach(self, parent):
        bg = parent["bg"]
        tk.Label(parent, text="Hilfeanfragen (älteste zuerst)", bg=bg, anchor="w",
                 font=("TkDefaultFont", 10, "bold")).pack(fill="x")
        self.queue_frame = tk.Frame(parent, bg=bg, pady=4)
        self.queue_frame.pack(fill="x")
        self._render_queue()

    # ------------------------------------------------------------------
    # Aktionen (Knöpfe)
    # ------------------------------------------------------------------
    def toggle_status(self):
        new = "busy" if self.me["status"] == "online" else "online"
        self.net.set_status(new)
        self._update_status_button()

    def ask_for_help(self):
        coaches = [p for p in self.peers.values()
                   if p["role"] == "coach" and self._shown_status(p) != "offline"]
        if not coaches:
            self._show_request_info("Kein Coach online.")
            return
        text = self.help_text.get().strip()[:P.MAX_TEXT]
        self.requests.clear()  # nur die neueste Anfrage anzeigen
        # An JEDEN Coach einzeln schicken – jeder bestätigt selbst.
        for c in coaches:
            help_id = self.net.send_help(c["ip"], c["port"], text)
            self.requests[help_id] = {"coach": c["name"], "state": "sending", "tries": 1}
        self.help_text.delete(0, "end")
        self._render_requests()

    def mark_done(self, help_id):
        for item in self.queue:
            if item["help_id"] == help_id:
                self.queue.remove(item)
                self.net.send_done(item["ip"], item["port"], help_id)
                break
        self._render_queue()

    def quit(self):
        self.net.stop()      # sendet "bye"
        self.root.destroy()

    # ------------------------------------------------------------------
    # Ereignisse aus dem Netzwerk verarbeiten (läuft im Hauptthread!)
    # ------------------------------------------------------------------
    def _poll(self):
        changed_peers = changed_queue = changed_requests = False
        try:
            while True:  # alle wartenden Ereignisse abholen
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "peer":
                    info = ev[1]
                    info["last_seen"] = time.monotonic()
                    self.peers[info["peer_id"]] = info
                    changed_peers = True
                elif kind == "bye":
                    if ev[1] in self.peers:
                        self.peers[ev[1]]["last_seen"] = 0  # sofort offline
                        changed_peers = True
                elif kind == "help":
                    item = ev[1]
                    if not any(q["help_id"] == item["help_id"] for q in self.queue):
                        item["time"] = time.strftime("%H:%M")
                        self.queue.append(item)  # hinten anhängen = älteste vorne
                        changed_queue = True
                        self.root.bell()
                elif kind in ("sending", "acked", "failed"):
                    r = self.requests.get(ev[1])
                    if r and r["state"] not in ("acked", "done"):
                        r["state"] = kind
                        if kind == "sending":
                            r["tries"] = ev[2]
                        changed_requests = True
                elif kind == "done":
                    r = self.requests.get(ev[1])
                    if r:
                        r["state"] = "done"
                        changed_requests = True
                elif kind == "log":
                    print(ev[1])
        except queue.Empty:
            pass

        if changed_peers:
            self._render_peers()
        if changed_queue:
            self._render_queue()
        if changed_requests:
            self._render_requests()
        self.root.after(100, self._poll)  # in 100 ms wieder nachschauen

    def _tick(self):
        """Jede Sekunde neu zeichnen, damit 'offline' (grau) erscheint."""
        self._render_peers()
        self.root.after(1000, self._tick)

    def _shown_status(self, peer):
        if time.monotonic() - peer["last_seen"] > P.OFFLINE_AFTER:
            return "offline"
        return peer["status"]

    # ------------------------------------------------------------------
    # Anzeige neu zeichnen
    # ------------------------------------------------------------------
    def _update_status_button(self):
        s = self.me["status"]
        self.status_btn.configure(text="● " + STATUS_TEXT[s], fg=COLORS[s],
                                  activeforeground=COLORS[s])

    def _render_peers(self):
        for w in self.peer_frame.winfo_children():
            w.destroy()
        bg = self.peer_frame["bg"]
        if not self.peers:
            tk.Label(self.peer_frame, text="Noch niemand gefunden …", fg="#777",
                     bg=bg).pack(anchor="w")
            return
        # Sortierung: Coaches zuerst, dann nach Name
        for p in sorted(self.peers.values(), key=lambda p: (p["role"] != "coach", p["name"].lower())):
            status = self._shown_status(p)
            row = tk.Frame(self.peer_frame, bg=bg)
            row.pack(fill="x", pady=2)
            dot(row, COLORS[status]).pack(side="left", padx=(0, 8))
            label = p["name"] + ("  (Coach)" if p["role"] == "coach" else "")
            tk.Label(row, text=label, bg=bg,
                     fg="#999" if status == "offline" else "black").pack(side="left")
            tk.Label(row, text=STATUS_TEXT[status], bg=bg, fg="#777").pack(side="right")

    def _render_queue(self):
        for w in self.queue_frame.winfo_children():
            w.destroy()
        bg = self.queue_frame["bg"]
        if not self.queue:
            tk.Label(self.queue_frame, text="Keine offenen Anfragen.", fg="#777",
                     bg=bg).pack(anchor="w")
            return
        for i, item in enumerate(self.queue, start=1):
            row = tk.Frame(self.queue_frame, bg="#fff4e0", padx=6, pady=4)
            row.pack(fill="x", pady=2)
            text = "%d. %s  %s" % (i, item["time"], item["name"])
            if item["text"]:
                text += ": " + item["text"]
            tk.Label(row, text=text, bg=row["bg"], anchor="w", justify="left",
                     wraplength=270).pack(side="left", fill="x", expand=True)
            tk.Button(row, text="Erledigt", cursor="hand2",
                      command=lambda h=item["help_id"]: self.mark_done(h)).pack(side="right")

    def _show_request_info(self, text):
        for w in self.request_frame.winfo_children():
            w.destroy()
        tk.Label(self.request_frame, text=text, bg=self.request_frame["bg"],
                 fg="#b00").pack(anchor="w")

    def _render_requests(self):
        for w in self.request_frame.winfo_children():
            w.destroy()
        bg = self.request_frame["bg"]
        texts = {
            "sending": ("#777", "wird gesendet … (Versuch {tries}/%d)" % P.MAX_TRIES),
            "acked": ("#2e9e44", "✓ angekommen"),
            "failed": ("#b00", "✗ nicht angekommen – bitte nochmal versuchen"),
            "done": ("#2e9e44", "✓ erledigt"),
        }
        for r in self.requests.values():
            color, t = texts[r["state"]]
            tk.Label(self.request_frame, text="%s: %s" % (r["coach"], t.format(tries=r["tries"])),
                     bg=bg, fg=color, anchor="w").pack(fill="x")
