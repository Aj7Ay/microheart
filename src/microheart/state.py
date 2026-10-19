"""VM registry (SQLite, standard library) and per-VM addressing.

Each VM gets an index. The index decides its /30 network, its TAP device and its MAC address.
The UNIQUE index column makes two VMs on one host impossible to clash, also with parallel commands.
"""
import re
import sqlite3
import time
from pathlib import Path

from . import assets

SUBNETS = 16384            # /30 blocks inside 172.16.0.0/16
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def validate_name(name: str) -> str:
    if not _NAME.match(name or ""):
        raise ValueError(f"bad VM name {name!r}: use 1-31 chars of a-z, 0-9 and '-', starting with a letter or digit")
    return name


def addresses(idx: int):
    """Return (host_ip, guest_ip) of the /30 block number idx. Index 0 gives 172.16.0.1 and 172.16.0.2."""
    base = idx * 4
    third, fourth = divmod(base, 256)
    return f"172.16.{third}.{fourth + 1}", f"172.16.{third}.{fourth + 2}"


def guest_mac(idx: int) -> str:
    third, fourth = divmod(idx * 4, 256)
    return "06:00:AC:10:%02X:%02X" % (third, fourth + 2)


def tap_name(idx: int) -> str:
    return f"mh{idx}"


class Registry:
    def __init__(self, path=None):
        path = Path(path) if path else assets.cache_dir() / "state.db"
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS vms ("
                        "name TEXT PRIMARY KEY, idx INTEGER UNIQUE NOT NULL, pid INTEGER, created REAL NOT NULL)")

    def create(self, name: str) -> dict:
        validate_name(name)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM vms WHERE name=?", (name,)).fetchone():
                raise ValueError(f"VM {name!r} already exists")
            used = {r[0] for r in self.db.execute("SELECT idx FROM vms")}
            idx = next((i for i in range(SUBNETS) if i not in used), None)
            if idx is None:
                raise RuntimeError("no free address block")
            self.db.execute("INSERT INTO vms (name, idx, pid, created) VALUES (?, ?, NULL, ?)",
                            (name, idx, time.time()))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(name)

    def get(self, name: str):
        row = self.db.execute("SELECT * FROM vms WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def list(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM vms ORDER BY idx")]

    def set_pid(self, name: str, pid) -> None:
        self.db.execute("UPDATE vms SET pid=? WHERE name=?", (pid, name))

    def delete(self, name: str) -> None:
        self.db.execute("DELETE FROM vms WHERE name=?", (name,))

    def close(self) -> None:
        self.db.close()
