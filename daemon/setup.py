"""
py2app-Buildkonfiguration fuer die claude-monitor Menueleisten-App.

Bauen: python3 setup.py py2app
Ergebnis: dist/claude-monitor.app
"""

from setuptools import setup

APP = ["menubar_app.py"]
OPTIONS = {
    "argv_emulation": False,
    "strip": True,
    "excludes": ["tkinter", "setuptools", "pip", "wheel"],
    "plist": {
        "CFBundleName": "claude-monitor",
        "CFBundleIdentifier": "de.599media.claude-monitor",
        "LSUIElement": True,  # nur Menueleiste, kein Dock-Icon
        "NSBluetoothAlwaysUsageDescription": (
            "claude-monitor sendet Nutzungsdaten per Bluetooth an das "
            "ESP32-Display."
        ),
    },
    "packages": ["rumps", "bleak"],
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
