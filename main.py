"""
SCHRITT 5: Der Startpunkt

Starten:
    python3 main.py                              -> fragt Name und Rolle ab
    python3 main.py --name Lena --role student
    python3 main.py --name "Herr Keller" --role coach

Zum Üben (simuliert 30 % Paketverlust, damit man die Wiederholungen sieht):
    python3 main.py --name Tim --role student --verlust 0.3
"""

import argparse
import queue
import sys
import tkinter as tk

import protocol as P
from gui import App
from network import Network


def ask_name_and_role(name, role):
    """Kleines Startfenster für Name und Rolle. Gibt (name, role) oder None zurück."""
    result = {}
    win = tk.Tk()
    win.title("Klassenzimmer – Start")
    win.resizable(False, False)
    frame = tk.Frame(win, padx=20, pady=16)
    frame.pack()

    tk.Label(frame, text="Dein Name:").grid(row=0, column=0, sticky="w")
    name_var = tk.StringVar(value=name or "")
    entry = tk.Entry(frame, textvariable=name_var, width=24)
    entry.grid(row=1, column=0, columnspan=2, pady=(2, 10), sticky="we")
    entry.focus()

    tk.Label(frame, text="Rolle:").grid(row=2, column=0, sticky="w")
    role_var = tk.StringVar(value=role or "student")
    tk.Radiobutton(frame, text="Schüler/in", variable=role_var, value="student").grid(row=3, column=0, sticky="w")
    tk.Radiobutton(frame, text="Coach", variable=role_var, value="coach").grid(row=3, column=1, sticky="w")

    error = tk.Label(frame, text="", fg="#b00")
    error.grid(row=4, column=0, columnspan=2, sticky="w")

    def ok(_event=None):
        n = P.clean_name(name_var.get())
        if not n:
            error.configure(text="Bitte einen Namen eingeben.")
            return
        result["name"], result["role"] = n, role_var.get()
        win.destroy()

    tk.Button(frame, text="Los geht's", command=ok).grid(row=5, column=0, columnspan=2, pady=(8, 0), sticky="we")
    win.bind("<Return>", ok)
    win.mainloop()
    return (result["name"], result["role"]) if result else None


def main():
    parser = argparse.ArgumentParser(description="Peer-to-Peer-App fürs Klassenzimmer")
    parser.add_argument("--name", help="dein Name")
    parser.add_argument("--role", choices=P.ROLES, help="student oder coach")
    parser.add_argument("--broadcast", default="255.255.255.255",
                        help="Broadcast-Adresse (Standard: 255.255.255.255)")
    parser.add_argument("--port", type=int, default=0,
                        help="fester Port für direkte Nachrichten, z.B. 50506 (Standard: zufällig)")
    parser.add_argument("--verlust", type=float, default=0.0,
                        help="zum Üben: Anteil verlorener Pakete, z.B. 0.3")
    args = parser.parse_args()

    name, role = P.clean_name(args.name or ""), args.role
    if not name or not role:
        answer = ask_name_and_role(name, role)
        if answer is None:
            sys.exit(0)  # Startfenster wurde geschlossen
        name, role = answer

    # "me" beschreibt diese App-Instanz. peer_id ist bei jedem Start neu.
    me = {"peer_id": P.new_id(), "name": name, "role": role, "status": "online"}
    events = queue.Queue()

    net = Network(me, events, broadcast_addr=args.broadcast, loss=args.verlust, port=args.port)
    try:
        net.start()
    except OSError as e:
        print("Netzwerk konnte nicht gestartet werden:", e)
        sys.exit(1)

    root = tk.Tk()
    App(root, me, net, events)
    try:
        root.mainloop()
    except KeyboardInterrupt:  # Ctrl+C im Terminal
        net.stop()


if __name__ == "__main__":
    main()
