#!/usr/bin/env python3
"""
Claude Usage Daemon als Menueleisten-App.

Fuehrt den Poll-Loop aus usage_daemon_core.run_forever() in einem
Hintergrund-Thread aus und zeigt Current-/Weekly-Auslastung im
Menueleisten-Titel an. print()-Ausgaben von usage_daemon_core landen (ohne
Terminal) in LOG_FILE.

Bauen: python3 setup.py py2app
Danach die .app aus dist/ einmalig unter Systemeinstellungen -> Allgemein ->
Login-Objekte hinzufuegen, damit sie automatisch bei Login startet.
"""

import subprocess
import sys
import threading
from pathlib import Path

import rumps

import usage_daemon_core as core

LOG_FILE = Path.home() / "Library" / "Logs" / "claude-monitor-daemon.log"


class ClaudeUsageMenuBarApp(rumps.App):
    def __init__(self):
        super().__init__("claude-monitor", title="claude-monitor …")
        self.menu = ["Jetzt aktualisieren", "Log oeffnen"]
        threading.Thread(target=core.main, daemon=True).start()
        self.timer = rumps.Timer(self._refresh_title, 5)
        self.timer.start()

    def _refresh_title(self, _sender):
        s = core.state
        if not s["ok"]:
            self.title = "⚠️ claude-monitor"
            return
        self.title = f"5h {s['current']}% · 7d {s['weekly']}%"

    @rumps.clicked("Jetzt aktualisieren")
    def refresh_now(self, _sender):
        try:
            core.poll_once()
        except Exception as exc:
            print(f"[menubar_app] manueller Poll fehlgeschlagen: {exc}")
            core.state["ok"] = False
        self._refresh_title(_sender)

    @rumps.clicked("Log oeffnen")
    def open_log(self, _sender):
        subprocess.run(["open", str(LOG_FILE)])


def _redirect_output_to_log() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    sys.stdout = log
    sys.stderr = log


if __name__ == "__main__":
    _redirect_output_to_log()
    ClaudeUsageMenuBarApp().run()
