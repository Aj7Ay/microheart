import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from microheart import pool as poolmod
from microheart.state import Registry, validate_pool


class RegistryPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.reg = Registry(self.path)

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def ready(self, pool, n):
        for name in self.reg.reserve(pool)[:n]:
            self.reg.set_state(name, "ready")

    def test_pool_name_rules(self):
        self.assertEqual(validate_pool("python"), "python")
        for bad in ("", "Py", "a" * 21, "a b", "-x"):
            with self.assertRaises(ValueError):
                validate_pool(bad)

    def test_duplicate_pool_and_bad_size(self):
        self.reg.pool_create("p", 2, 1, 256)
        with self.assertRaises(ValueError):
            self.reg.pool_create("p", 2, 1, 256)
        with self.assertRaises(ValueError):
            self.reg.pool_create("q", 0, 1, 256)

    def test_reserve_fills_to_size_and_no_more(self):
        self.reg.pool_create("p", 3, 1, 256)
        first = self.reg.reserve("p")
        self.assertEqual(len(first), 3)
        self.assertEqual(self.reg.reserve("p"), [])            # booting VMs count as live
        self.assertEqual(self.reg.counts("p")["booting"], 3)

    def test_two_refills_never_overshoot(self):
        self.reg.pool_create("p", 3, 1, 256)
        other = Registry(self.path)
        got = self.reg.reserve("p") + other.reserve("p") + self.reg.reserve("p")
        other.close()
        self.assertEqual(len(got), 3)
        self.assertEqual(len({r["idx"] for r in self.reg.vms_in_pool("p")}), 3)

    def test_leased_vms_do_not_count_so_the_pool_refills(self):
        self.reg.pool_create("p", 2, 1, 256)
        self.ready("p", 2)
        self.assertEqual(self.reg.lease("p") is not None, True)
        self.assertEqual(len(self.reg.reserve("p")), 1)

    def test_lease_is_exclusive(self):
        self.reg.pool_create("p", 2, 1, 256)
        self.ready("p", 2)
        other = Registry(self.path)
        a, b, c = self.reg.lease("p"), other.lease("p"), self.reg.lease("p")
        other.close()
        self.assertNotEqual(a, b)
        self.assertIsNone(c)
        self.assertEqual(self.reg.counts("p")["leased"], 2)

    def test_lease_ignores_booting_vms(self):
        self.reg.pool_create("p", 2, 1, 256)
        self.reg.reserve("p")
        self.assertIsNone(self.reg.lease("p"))

    def test_reserve_unknown_pool(self):
        with self.assertRaises(RuntimeError):
            self.reg.reserve("nope")

    def test_database_from_0_2_is_migrated(self):
        old = Path(self.tmp.name) / "old.db"
        db = sqlite3.connect(str(old))
        db.execute("CREATE TABLE vms (name TEXT PRIMARY KEY, idx INTEGER UNIQUE NOT NULL, pid INTEGER, created REAL NOT NULL)")
        db.execute("INSERT INTO vms VALUES ('a', 0, 5, 1.0)")
        db.commit()
        db.close()
        reg = Registry(old)
        rec = reg.get("a")
        self.assertEqual((rec["pool"], rec["state"]), (None, "running"))
        reg.close()


class PoolLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Registry(Path(self.tmp.name) / "state.db")
        self.reg.pool_create("p", 2, 1, 256)

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_lease_returns_a_live_vm(self):
        name = self.reg.reserve("p")[0]
        self.reg.set_state(name, "ready")
        with mock.patch.object(poolmod.MicroVM, "running", return_value=True):
            self.assertEqual(poolmod.lease(self.reg, "p", "/d", "/k", queue_timeout=1), name)

    def test_lease_drops_a_dead_ready_vm_and_takes_the_next(self):
        dead, live = self.reg.reserve("p")
        self.reg.set_state(dead, "ready")
        self.reg.set_state(live, "ready")
        cleaned = []
        with mock.patch.object(poolmod.MicroVM, "running", lambda vm: vm.name == live), \
                mock.patch.object(poolmod.MicroVM, "clean", lambda vm: (cleaned.append(vm.name), vm.registry.delete(vm.name))):
            got = poolmod.lease(self.reg, "p", "/d", "/k", queue_timeout=1)
        self.assertEqual(got, live)
        self.assertEqual(cleaned, [dead])

    def test_lease_times_out_with_a_clear_error_and_asks_for_a_refill(self):
        with mock.patch.object(poolmod, "spawn_refill") as spawn:
            with self.assertRaises(TimeoutError) as e:
                poolmod.lease(self.reg, "p", "/d", "/k", queue_timeout=0.2, poll=0.05)
        self.assertIn("no ready VM", str(e.exception))
        spawn.assert_called_once()

    def test_lease_unknown_pool(self):
        with self.assertRaises(RuntimeError):
            poolmod.lease(self.reg, "nope", "/d", "/k", queue_timeout=0.1)

    def test_reap_removes_dead_ready_and_old_booting_but_not_young_booting(self):
        a, b = self.reg.reserve("p")
        self.reg.set_state(a, "ready")                       # dead, ready  -> removed
        self.reg.db.execute("UPDATE vms SET created=created-1000 WHERE name=?", (b,))   # dead, old booting -> removed
        with mock.patch.object(poolmod.MicroVM, "running", return_value=False), \
                mock.patch.object(poolmod.MicroVM, "clean", lambda vm: vm.registry.delete(vm.name)):
            self.assertEqual(sorted(poolmod.reap(self.reg, "p")), sorted([a, b]))
            c = self.reg.reserve("p")[0]                      # young booting, dead process -> kept
            self.assertEqual(poolmod.reap(self.reg, "p"), [])
        self.assertIsNotNone(self.reg.get(c))

    def test_refill_boots_the_missing_vms_and_reports_failures(self):
        def fake_start(vm, wait=60, reserved=False):
            if vm.name.endswith("0") or vm.name.endswith("1") or vm.name.endswith("2"):
                raise RuntimeError("boom\nsecond line")
            vm.registry.set_state(vm.name, "ready")
        with mock.patch.object(poolmod.MicroVM, "start", fake_start), \
                mock.patch.object(poolmod, "reap", return_value=[]):
            results = poolmod.refill(self.reg, "p", "/d", "/k")
        self.assertEqual(len(results), 2)
        for name, err in results:
            self.assertTrue(err is None or err == "boom")

    def test_delete_removes_pool_first_then_vms(self):
        for n in self.reg.reserve("p"):
            self.reg.set_state(n, "leased")
        with mock.patch.object(poolmod.MicroVM, "clean", lambda vm: vm.registry.delete(vm.name)):
            self.assertEqual(poolmod.delete(self.reg, "p"), 2)
        self.assertIsNone(self.reg.pool_get("p"))
        self.assertEqual(self.reg.list(), [])

    def test_scale_down_destroys_only_surplus_ready_vms(self):
        for n in self.reg.reserve("p"):
            self.reg.set_state(n, "ready")
        with mock.patch.object(poolmod.MicroVM, "clean", lambda vm: vm.registry.delete(vm.name)), \
                mock.patch.object(poolmod, "refill", return_value=[]):
            poolmod.scale(self.reg, "p", 1, "/d", "/k")
        self.assertEqual(len(self.reg.vms_in_pool("p")), 1)
        self.assertEqual(self.reg.pool_get("p")["size"], 1)


if __name__ == "__main__":
    unittest.main()
