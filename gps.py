"""GPS position from gpsd (the standard Linux GPS service).

gpsd handles the receiver itself (USB stick, serial HAT, ...); this module
just reads its JSON stream on localhost:2947 in a background thread and keeps
the latest fix. No extra Python packages are needed.
"""

import json
import socket
import threading
import time
from dataclasses import dataclass

RECONNECT_S = 5.0


@dataclass
class Fix:
    lat: float
    lon: float
    mode: int  # 2 = 2D fix, 3 = 3D fix
    when: float  # time.monotonic() when received


class GpsReader:
    def __init__(self, host: str = "127.0.0.1", port: int = 2947):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._fix: Fix | None = None
        self._connected = False
        self._satellites = 0
        self._started = False

    def start(self) -> None:
        """Safe to call repeatedly; the thread starts once, on first use."""
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, name="gps", daemon=True).start()

    def latest(self) -> Fix | None:
        with self._lock:
            return self._fix

    def status(self) -> str:
        """One-line human-readable state, for the panel and web page."""
        if not self._started:
            return "GPS off"
        with self._lock:
            fix, connected, sats = self._fix, self._connected, self._satellites
        if not connected:
            return "GPS: no gpsd (is it installed and running?)"
        if fix is None:
            return f"GPS: searching ({sats} satellites)"
        age = time.monotonic() - fix.when
        if age > 10:
            return f"GPS: fix lost {int(age)}s ago ({sats} satellites)"
        return f"GPS: {fix.mode}D fix, {sats} satellites"

    def _run(self) -> None:
        while True:
            try:
                with socket.create_connection((self.host, self.port), timeout=10) as sock:
                    sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    with self._lock:
                        self._connected = True
                    for line in sock.makefile("r", encoding="utf-8", errors="replace"):
                        self._handle(line)
            except OSError:
                pass
            with self._lock:
                self._connected = False
            time.sleep(RECONNECT_S)

    def _handle(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            return
        cls = msg.get("class")
        if cls == "TPV" and msg.get("mode", 0) >= 2 and "lat" in msg and "lon" in msg:
            fix = Fix(float(msg["lat"]), float(msg["lon"]), int(msg["mode"]), time.monotonic())
            with self._lock:
                self._fix = fix
        elif cls == "SKY":
            sats = msg.get("uSat")
            if sats is None:
                sats = sum(1 for s in msg.get("satellites") or [] if s.get("used"))
            with self._lock:
                self._satellites = int(sats)
