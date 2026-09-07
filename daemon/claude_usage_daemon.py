#!/usr/bin/env python3
"""
Claude Usage Daemon fuer claude-monitor.

Liest das Claude Code OAuth-Token aus der macOS Keychain, fragt bei
api.anthropic.com die Rate-Limit-Header ab und stellt Current-(5h)- und
Weekly-(7d)-Auslastung als JSON ueber einen lokalen HTTP-Endpoint bereit.
Das ESPHome-Geraet pollt diesen Endpoint - das Anthropic-Token verlaesst
diesen Rechner nie.

Zusaetzlich wird bei jedem Poll versucht, dieselben Werte per BLE an den
ESP32 zu schreiben (Fallback, falls das Geraet nicht per WLAN erreichbar
ist). Dafuer wird "bleak" benoetigt: pip install bleak

Technik (Keychain-Zugriff, Header-Namen, Request-Body) uebernommen aus
https://github.com/HermannBjorgvin/Clawdmeter (daemon/claude_usage_daemon.py),
hier neu geschrieben fuer einen lokalen HTTP-Endpoint plus optionalen
BLE-Fallback.

Start: python3 claude_usage_daemon.py
Stop:  Ctrl+C
"""

import asyncio
import getpass
import http.server
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from bleak import BleakClient, BleakScanner

KEYCHAIN_SERVICE = "Claude Code-credentials"
POLL_INTERVAL_S = 60
LISTEN_PORT = 8787
SECRET_FILE = Path(__file__).parent / "secret.txt"

BLE_DEVICE_NAME = "claude-monitor"
BLE_CHARACTERISTIC_UUID = "c1a0d001-0000-1000-8000-00805f9b34fb"
BLE_SCAN_TIMEOUT_S = 5

_lock = threading.Lock()
_state = {
    "current": 0,
    "current_reset_min": 0,
    "weekly": 0,
    "weekly_reset_min": 0,
    "ok": False,
}


def _load_shared_secret() -> str:
    if not SECRET_FILE.exists():
        raise SystemExit(
            f"Fehlt: {SECRET_FILE}. Muss den gleichen Wert enthalten wie "
            "'usage_daemon_secret' in secrets.yaml."
        )
    return SECRET_FILE.read_text().strip()


def _read_access_token() -> str:
    raw = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            getpass.getuser(),
            "-w",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return json.loads(raw)["claudeAiOauth"]["accessToken"]


def _reset_minutes(reset_header: str | None) -> int:
    if not reset_header:
        return 0
    try:
        reset_ts = float(reset_header)
    except ValueError:
        return 0
    minutes = (reset_ts - time.time()) / 60.0
    return int(round(minutes)) if minutes > 0 else 0


def _pct(utilization_header: str | None) -> int:
    if not utilization_header:
        return 0
    try:
        return int(round(float(utilization_header) * 100))
    except ValueError:
        return 0


def _poll_once() -> None:
    token = _read_access_token()
    body = json.dumps(
        {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
        headers={
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
            "User-Agent": "claude-code/2.1.5",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        headers = resp.headers
        resp.read()

    with _lock:
        _state.update(
            {
                "current": _pct(headers.get("anthropic-ratelimit-unified-5h-utilization")),
                "current_reset_min": _reset_minutes(headers.get("anthropic-ratelimit-unified-5h-reset")),
                "weekly": _pct(headers.get("anthropic-ratelimit-unified-7d-utilization")),
                "weekly_reset_min": _reset_minutes(headers.get("anthropic-ratelimit-unified-7d-reset")),
                "ok": True,
            }
        )


async def _push_via_ble(payload: bytes) -> None:
    device = await BleakScanner.find_device_by_name(
        BLE_DEVICE_NAME, timeout=BLE_SCAN_TIMEOUT_S
    )
    if device is None:
        return
    async with BleakClient(device) as client:
        await client.write_gatt_char(BLE_CHARACTERISTIC_UUID, payload, response=False)


def _poll_loop() -> None:
    ble_loop = asyncio.new_event_loop()
    while True:
        try:
            _poll_once()
        except Exception as exc:  # Daemon soll bei Fehlern weiterlaufen
            print(f"[claude-usage-daemon] Poll fehlgeschlagen: {exc}")
            with _lock:
                _state["ok"] = False
        try:
            with _lock:
                payload = json.dumps(_state).encode("utf-8")
            ble_loop.run_until_complete(_push_via_ble(payload))
        except Exception as exc:  # BLE ist nur Fallback, WLAN-Pfad bleibt unberuehrt
            print(f"[claude-usage-daemon] BLE-Push fehlgeschlagen: {exc}")
        time.sleep(POLL_INTERVAL_S)


def _make_handler(shared_secret: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/usage":
                self.send_response(404)
                self.end_headers()
                return
            if self.headers.get("X-Auth") != shared_secret:
                self.send_response(401)
                self.end_headers()
                return
            with _lock:
                payload = json.dumps(_state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # kein Access-Log auf stdout
            pass

    return Handler


def main() -> None:
    shared_secret = _load_shared_secret()
    threading.Thread(target=_poll_loop, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), _make_handler(shared_secret))
    print(f"[claude-usage-daemon] Laeuft auf Port {LISTEN_PORT}, Poll alle {POLL_INTERVAL_S}s")
    server.serve_forever()


if __name__ == "__main__":
    main()
