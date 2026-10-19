import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from microheart import vm as vmmod
from microheart.state import Registry


class VMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Registry(Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def make(self, name="a"):
        return vmmod.MicroVM(name, "/base.ext4", "/key", registry=self.reg, run_dir=self.tmp.name)

    def test_start_needs_root(self):
        with mock.patch.object(vmmod.os, "geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                self.make().start()
        self.assertEqual(self.reg.list(), [])

    def test_failed_start_leaves_no_record_and_no_network(self):
        vm = self.make()
        with mock.patch.object(vmmod.os, "geteuid", return_value=0), \
                mock.patch.object(vmmod.os, "access", return_value=True), \
                mock.patch.object(vmmod.assets, "firecracker_path", return_value=Path("/fc")), \
                mock.patch.object(vmmod, "_clone", side_effect=OSError("disk full")), \
                mock.patch.object(vmmod.net, "down") as down:
            with self.assertRaises(OSError):
                vm.start()
        self.assertEqual(self.reg.list(), [])
        self.assertFalse(vm.dir.exists())
        self.assertEqual(down.call_count, 1)
        self.assertEqual(down.call_args[0][0], "mh0")
        self.assertTrue(down.call_args[1]["remove_nat"]())      # no other VM: the NAT rule may go

    def clean_and_collect_iptables_calls(self, name):
        calls = []
        with mock.patch.object(vmmod.net, "_run", side_effect=lambda *c, **k: calls.append(c)), \
                mock.patch.object(vmmod.net, "_locked", contextlib.nullcontext), \
                mock.patch.object(vmmod.net, "host_iface", return_value="eth0"):
            self.make(name).clean()
        return [c for c in calls if c[0] == "iptables"]

    def test_nat_rule_stays_while_another_vm_exists(self):
        self.reg.create("a")
        self.reg.create("b")
        self.assertEqual(self.clean_and_collect_iptables_calls("a"), [])
        self.assertEqual([r["name"] for r in self.reg.list()], ["b"])

    def test_nat_rule_is_removed_with_the_last_vm(self):
        self.reg.create("a")
        calls = self.clean_and_collect_iptables_calls("a")
        self.assertEqual(len(calls), 1)
        self.assertIn("-D", calls[0])

    def stop_without_key(self, name="a", survives_sigterm=False):
        """Run the real stop() on a VM object that has no SSH key. Return (ssh mock, kill mock)."""
        self.reg.create(name)
        vm = vmmod.MicroVM(name, registry=self.reg, run_dir=self.tmp.name)       # no key, like pool delete
        alive = {"v": True}
        kills = []

        def fake_kill(pid, sig):
            kills.append(sig)
            if sig == vmmod.signal.SIGKILL or (sig == vmmod.signal.SIGTERM and not survives_sigterm):
                alive["v"] = False

        with mock.patch.object(vmmod.MicroVM, "pid", lambda s: 4242 if alive["v"] else None), \
                mock.patch.object(vmmod.MicroVM, "ssh") as ssh, \
                mock.patch.object(vmmod.os, "kill", fake_kill), \
                mock.patch.object(vmmod.time, "sleep"):
            vm.stop()
        return ssh, kills

    def test_stop_without_key_does_not_use_ssh_and_stops_the_process(self):
        ssh, kills = self.stop_without_key()
        ssh.assert_not_called()
        self.assertEqual(kills, [vmmod.signal.SIGTERM])

    def test_stop_uses_sigkill_when_sigterm_is_ignored(self):
        _, kills = self.stop_without_key(survives_sigterm=True)
        self.assertEqual(kills, [vmmod.signal.SIGTERM, vmmod.signal.SIGKILL])

    def test_ssh_argv_without_key_is_a_clear_error(self):
        self.reg.create("a")
        vm = vmmod.MicroVM("a", registry=self.reg, run_dir=self.tmp.name)
        with self.assertRaises(RuntimeError):
            vm.ssh_argv("true")

    def test_two_vms_get_different_addresses(self):
        self.reg.create("a")
        self.reg.create("b")
        self.assertNotEqual(self.make("a").guest_ip, self.make("b").guest_ip)
        self.assertNotEqual(self.make("a").tap, self.make("b").tap)

    def test_boot_args_carry_the_address(self):
        self.reg.create("a")
        self.reg.create("b")
        with mock.patch.object(vmmod.assets, "kernel_path", return_value=Path("/k")):
            cfg = self.make("b").config(Path("/d.ext4"))
        args = cfg["boot-source"]["boot_args"]
        self.assertIn("microheart.ip=172.16.0.6/30", args)
        self.assertIn("microheart.gw=172.16.0.5", args)
        self.assertIn("microheart.name=b", args)
        self.assertEqual(cfg["network-interfaces"][0]["host_dev_name"], "mh1")

    def test_ssh_command_is_quoted(self):
        self.reg.create("a")
        vm = self.make("a")
        with mock.patch.object(vmmod.subprocess, "run") as run:
            vm.run(["sh", "-c", "echo a; echo b"])
        self.assertEqual(run.call_args[0][0][-1], "sh -c 'echo a; echo b'")


if __name__ == "__main__":
    unittest.main()
