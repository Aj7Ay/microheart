"""VM and pool registry (SQLite, standard library) and per-VM addressing.

Each VM gets an index. The index decides its /30 network, its TAP device and its MAC address.
The UNIQUE index column makes two VMs on one host impossible to clash, also with parallel commands.
VM states: booting, ready (pool only), leased (pool only), running (not in a pool).
"""
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import assets

SUBNETS = 16384            # /30 blocks inside 172.16.0.0/16
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
_POOL = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")


def validate_name(name: str) -> str:
    if not _NAME.match(name or ""):
        raise ValueError(f"bad VM name {name!r}: use 1-31 chars of a-z, 0-9 and '-', starting with a letter or digit")
    return name


def validate_pool(name: str) -> str:
    if not _POOL.match(name or ""):
        raise ValueError(f"bad pool name {name!r}: use 1-20 chars of a-z, 0-9 and '-', starting with a letter or digit")
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
        self.path = Path(path) if path else assets.cache_dir() / "state.db"
        self.db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS vms ("
                        "name TEXT PRIMARY KEY, idx INTEGER UNIQUE NOT NULL, pid INTEGER, created REAL NOT NULL, "
                        "pool TEXT, state TEXT NOT NULL DEFAULT 'running')")
        self.db.execute("CREATE TABLE IF NOT EXISTS pools ("
                        "name TEXT PRIMARY KEY, size INTEGER NOT NULL, vcpu INTEGER NOT NULL, "
                        "mem INTEGER NOT NULL, created REAL NOT NULL)")
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(vms)")}
        if "pool" not in cols:                      # database from 0.2.x
            self.db.execute("ALTER TABLE vms ADD COLUMN pool TEXT")
        if "state" not in cols:
            self.db.execute("ALTER TABLE vms ADD COLUMN state TEXT NOT NULL DEFAULT 'running'")

    @contextmanager
    def _txn(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def _alloc(self) -> int:
        used = {r[0] for r in self.db.execute("SELECT idx FROM vms")}
        idx = next((i for i in range(SUBNETS) if i not in used), None)
        if idx is None:
            raise RuntimeError("no free address block")
        return idx

    # -- VMs -----------------------------------------------------------
    def create(self, name: str, pool=None, state="booting") -> dict:
        validate_name(name)
        with self._txn():
            if self.db.execute("SELECT 1 FROM vms WHERE name=?", (name,)).fetchone():
                raise ValueError(f"VM {name!r} already exists")
            self.db.execute("INSERT INTO vms (name, idx, pid, created, pool, state) VALUES (?, ?, NULL, ?, ?, ?)",
                            (name, self._alloc(), time.time(), pool, state))
        return self.get(name)

    def get(self, name: str):
        row = self.db.execute("SELECT * FROM vms WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def list(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM vms ORDER BY idx")]

    def set_pid(self, name: str, pid) -> None:
        self.db.execute("UPDATE vms SET pid=? WHERE name=?", (pid, name))

    def set_state(self, name: str, state: str) -> None:
        self.db.execute("UPDATE vms SET state=? WHERE name=?", (state, name))

    def delete(self, name: str) -> None:
        self.db.execute("DELETE FROM vms WHERE name=?", (name,))

    # -- pools ---------------------------------------------------------
    def pool_create(self, name: str, size: int, vcpu: int, mem: int) -> dict:
        validate_pool(name)
        if size < 1:
            raise ValueError("pool size must be at least 1")
        with self._txn():
            if self.db.execute("SELECT 1 FROM pools WHERE name=?", (name,)).fetchone():
                raise ValueError(f"pool {name!r} already exists")
            self.db.execute("INSERT INTO pools (name, size, vcpu, mem, created) VALUES (?, ?, ?, ?, ?)",
                            (name, size, vcpu, mem, time.time()))
        return self.pool_get(name)

    def pool_get(self, name: str):
        row = self.db.execute("SELECT * FROM pools WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def pools(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM pools ORDER BY name")]

    def pool_set_size(self, name: str, size: int) -> None:
        if size < 1:
            raise ValueError("pool size must be at least 1")
        self.db.execute("UPDATE pools SET size=? WHERE name=?", (size, name))

    def pool_delete(self, name: str) -> None:
        self.db.execute("DELETE FROM pools WHERE name=?", (name,))

    def vms_in_pool(self, pool: str):
        return [dict(r) for r in self.db.execute("SELECT * FROM vms WHERE pool=? ORDER BY created", (pool,))]

    def counts(self, pool: str) -> dict:
        out = {"booting": 0, "ready": 0, "leased": 0}
        for r in self.db.execute("SELECT state, COUNT(*) FROM vms WHERE pool=? GROUP BY state", (pool,)):
            out[r[0]] = r[1]
        return out

    def reserve(self, pool: str) -> list:
        """Insert as many 'booting' VM records as the pool lacks. Atomic: parallel refills never overshoot."""
        with self._txn():
            p = self.pool_get(pool)
            if p is None:
                raise RuntimeError(f"no pool named {pool!r}")
            live = self.db.execute("SELECT COUNT(*) FROM vms WHERE pool=? AND state IN ('booting', 'ready')",
                                   (pool,)).fetchone()[0]
            names = []
            for _ in range(max(0, p["size"] - live)):
                while True:
                    name = f"{pool}-{secrets.token_hex(3)}"
                    if not self.db.execute("SELECT 1 FROM vms WHERE name=?", (name,)).fetchone():
                        break
                self.db.execute("INSERT INTO vms (name, idx, pid, created, pool, state) VALUES (?, ?, NULL, ?, ?, 'booting')",
                                (name, self._alloc(), time.time(), pool))
                names.append(name)
        return names

    def lease(self, pool: str):
        """Take the oldest ready VM of the pool. Atomic: two callers never get the same VM."""
        with self._txn():
            row = self.db.execute("SELECT name FROM vms WHERE pool=? AND state='ready' ORDER BY created LIMIT 1",
                                  (pool,)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE vms SET state='leased' WHERE name=?", (row["name"],))
            return row["name"]

    def close(self) -> None:
        self.db.close()
