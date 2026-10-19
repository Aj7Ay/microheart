import tempfile
import unittest
from pathlib import Path

from microheart.state import Registry, addresses, guest_mac, tap_name, validate_name


class AddressTests(unittest.TestCase):
    def test_index_zero_matches_the_old_fixed_addresses(self):
        self.assertEqual(addresses(0), ("172.16.0.1", "172.16.0.2"))
        self.assertEqual(guest_mac(0), "06:00:AC:10:00:02")

    def test_next_blocks(self):
        self.assertEqual(addresses(1), ("172.16.0.5", "172.16.0.6"))
        self.assertEqual(addresses(63), ("172.16.0.253", "172.16.0.254"))
        self.assertEqual(addresses(64), ("172.16.1.1", "172.16.1.2"))
        self.assertEqual(guest_mac(64), "06:00:AC:10:01:02")

    def test_all_blocks_are_distinct(self):
        guests = {addresses(i)[1] for i in range(16384)}
        self.assertEqual(len(guests), 16384)
        self.assertEqual(len({guest_mac(i) for i in range(16384)}), 16384)

    def test_tap_name_fits_linux_limit(self):
        self.assertLessEqual(len(tap_name(16383)), 15)


class NameTests(unittest.TestCase):
    def test_good_names(self):
        for n in ("default", "api", "run-1a2b3c", "a" * 31):
            self.assertEqual(validate_name(n), n)

    def test_bad_names(self):
        for n in ("", "Api", "-x", "a b", "a/b", "../x", "a" * 32, "a;rm"):
            with self.assertRaises(ValueError):
                validate_name(n)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Registry(Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_create_gives_distinct_indexes(self):
        a, b = self.reg.create("a"), self.reg.create("b")
        self.assertEqual((a["idx"], b["idx"]), (0, 1))

    def test_duplicate_name_is_refused(self):
        self.reg.create("a")
        with self.assertRaises(ValueError):
            self.reg.create("a")
        self.assertEqual(len(self.reg.list()), 1)

    def test_freed_index_is_reused(self):
        self.reg.create("a")
        self.reg.create("b")
        self.reg.delete("a")
        self.assertEqual(self.reg.create("c")["idx"], 0)

    def test_pid_and_get(self):
        self.reg.create("a")
        self.reg.set_pid("a", 123)
        self.assertEqual(self.reg.get("a")["pid"], 123)
        self.assertIsNone(self.reg.get("missing"))

    def test_two_registry_objects_share_state(self):
        other = Registry(Path(self.tmp.name) / "state.db")
        self.reg.create("a")
        self.assertEqual(other.create("b")["idx"], 1)
        other.close()


if __name__ == "__main__":
    unittest.main()
