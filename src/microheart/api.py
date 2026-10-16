"""Tiny client for the Firecracker API on a Unix socket (standard library only)."""
from __future__ import annotations

import http.client
import json
import socket


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 5):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def request(sock_path: str, method: str, route: str, body: dict | None = None):
    conn = _UnixConn(sock_path)
    try:
        data = json.dumps(body) if body is not None else None
        conn.request(method, route, body=data, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode()
        if resp.status >= 300:
            raise RuntimeError(f"{method} {route} -> {resp.status}: {raw}")
        return json.loads(raw) if raw else None
    finally:
        conn.close()
