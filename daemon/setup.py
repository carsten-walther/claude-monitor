"""
py2app-Buildkonfiguration fuer die Claude Monitor Menueleisten-App.

Bauen: python3 setup.py py2app
Ergebnis: dist/Claude Monitor.app
"""

from setuptools import setup

APP = ["menubar_app.py"]
OPTIONS = {
    "argv_emulation": False,
    "strip": True,
    "excludes": ["tkinter", "setuptools", "pip", "wheel"],
    "iconfile": "claude-monitor.icns",
    "plist": {
        "CFBundleName": "Claude Monitor",
        "CFBundleIdentifier": "de.carstenwalther.claude-monitor",
        "LSUIElement": True,  # nur Menueleiste, kein Dock-Icon
        "NSBluetoothAlwaysUsageDescription": (
            "Claude Monitor sendet Nutzungsdaten per Bluetooth an das "
            "Claude Monitor-Display."
        ),
    },
    "packages": ["rumps", "bleak"],
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
