#!/usr/bin/env python3
"""
Claude Usage Daemon fuer claude-monitor - Kernlogik.

Liest das Claude Code OAuth-Token aus der macOS Keychain, fragt bei
api.anthropic.com die Rate-Limit-Header ab und schreibt Current-(5h)- und
Weekly-(7d)-Auslastung als JSON per BLE an den ESP32 (Characteristic-Write,
siehe esp32_ble_server in claude-monitor.yaml). Kein WLAN, kein HTTP-Endpoint -
das Anthropic-Token verlaesst diesen Rechner nie. Dafuer wird "bleak"
benoetigt: pip install bleak

Wird von claude_usage_daemon.py (CLI) und menubar_app.py (Menueleisten-App)
importiert.
"""

import asyncio
import getpass
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from bleak import BleakClient, BleakScanner

KEYCHAIN_SERVICE = "Claude Code-credentials"
# BLE-Push (inkl. waiting-Status aus STATUS_FILE) und Token-Poll (Anthropic-API)
# laufen unabhaengig: das BLE-Device soll zeitnah aktualisiert werden, die
# Token-Abfrage aber nicht bei jedem Zyklus unnoetig Rate-Limit-Kontingent ziehen.
BLE_PUSH_INTERVAL_S = 5
TOKEN_POLL_INTERVAL_S = 5 * 60

# Wird von ~/.local/bin/claude_hook.py (Claude-Code-Hooks) geschrieben.
STATUS_FILE = Path.home() / ".claude" / "claude-monitor-status.json"

BLE_DEVICE_NAME = "claude-monitor"
BLE_CHARACTERISTIC_UUID = "c1a0d001-0000-1000-8000-00805f9b34fb"
BLE_SCAN_TIMEOUT_S = 5
# find_device_by_name findet die Werbe-Pakete auch bei gutem Empfang nicht
# zuverlaessig in einem einzelnen Scan (empirisch: ~50% Fehlerquote bei 5s) -
# mehrere Versuche pro Zyklus gleichen das aus.
BLE_SCAN_RETRIES = 3

state = {
    "current": 0,
    "current_reset_min": 0,
    "weekly": 0,
    "weekly_reset_min": 0,
    "epoch": 0,
    "ok": False,
    "project": "",
    "waiting": False,
}


def _read_claude_status() -> dict:
    """Liest project/waiting aus der von claude_hook.py geschriebenen Datei.
    Fehlt sie oder ist sie kaputt, gilt: kein Projekt, nicht wartend."""
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "project": str(data.get("project", "")),
            "waiting": bool(data.get("waiting", False)),
        }
    except Exception:
        return {"project": "", "waiting": False}


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


def poll_once() -> None:
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

    state.update(
        {
            "current": _pct(headers.get("anthropic-ratelimit-unified-5h-utilization")),
            "current_reset_min": _reset_minutes(headers.get("anthropic-ratelimit-unified-5h-reset")),
            "weekly": _pct(headers.get("anthropic-ratelimit-unified-7d-utilization")),
            "weekly_reset_min": _reset_minutes(headers.get("anthropic-ratelimit-unified-7d-reset")),
            "ok": True,
        }
    )


async def _push_via_ble(payload: bytes) -> None:
    device = None
    for attempt in range(1, BLE_SCAN_RETRIES + 1):
        device = await BleakScanner.find_device_by_name(
            BLE_DEVICE_NAME, timeout=BLE_SCAN_TIMEOUT_S
        )
        if device is not None:
            break
        print(f"[claude-usage-daemon] '{BLE_DEVICE_NAME}' nicht gefunden (Versuch {attempt}/{BLE_SCAN_RETRIES})")
    if device is None:
        return
    async with BleakClient(device) as client:
        # response=True (bestaetigter GATT-Write) statt write-without-response:
        # unbestaetigte Writes kamen im Test wiederholt nie beim ESP32 an,
        # bestaetigte zuverlaessig.
        await client.write_gatt_char(BLE_CHARACTERISTIC_UUID, payload, response=True)


def run_forever() -> None:
    next_token_poll = 0.0
    while True:
        if time.time() >= next_token_poll:
            try:
                poll_once()
            except Exception as exc:  # Daemon soll bei Fehlern weiterlaufen
                print(f"[claude-usage-daemon] Poll fehlgeschlagen: {exc}")
                state["ok"] = False
            next_token_poll = time.time() + TOKEN_POLL_INTERVAL_S
        state["epoch"] = int(time.time())
        state.update(_read_claude_status())
        try:
            payload = json.dumps(state).encode("utf-8")
            # Frischer Event-Loop pro Zyklus: ein ueber die gesamte Laufzeit
            # wiederverwendeter Loop macht BleakScanner/CoreBluetooth auf macOS
            # nach einigen Dutzend Zyklen zunehmend unzuverlaessig (empirisch
            # geprueft: 2 von 6 Zyklen mit persistentem Loop schlugen fehl).
            asyncio.run(_push_via_ble(payload))
        except Exception as exc:
            print(f"[claude-usage-daemon] BLE-Push fehlgeschlagen: {exc}")
        time.sleep(BLE_PUSH_INTERVAL_S)


def main() -> None:
    print(
        f"[claude-usage-daemon] BLE-Push alle {BLE_PUSH_INTERVAL_S}s an "
        f"'{BLE_DEVICE_NAME}', Token-Poll alle {TOKEN_POLL_INTERVAL_S}s"
    )
    run_forever()
