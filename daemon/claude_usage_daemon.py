#!/usr/bin/env python3
"""
Claude Usage Daemon fuer claude-monitor - CLI-Einstiegspunkt.

Duenner Wrapper um usage_daemon_core fuer manuellen Start/Debugging ohne
App-Overhead (siehe menubar_app.py fuer die gebaute .app-Variante).
Die eigentliche Logik liegt in usage_daemon_core.py.

Start: python3 claude_usage_daemon.py
Stop:  Ctrl+C
"""

from usage_daemon_core import main

if __name__ == "__main__":
    main()
