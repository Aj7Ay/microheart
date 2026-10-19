import contextlib
import io
import subprocess
import types
import unittest
from unittest import mock

from microheart import cli


class FakeVM:
    def __init__(self, result=None, error=None, start_error=None):
        self.result, self.error, self.start_error = result, error, start_error
        self.cleaned, self.argv, self.name = False, None, None

    def start(self):
        if self.start_error:
            raise self.start_error

    def run(self, argv, timeout=60):
        self.argv = argv
        if self.error:
            raise self.error
        return self.result

    def clean(self):
        self.cleaned = True


def run_cli(vm, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(cli, "_vm", return_value=vm), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with mock.patch.object(cli.signal, "signal"):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
    return code, out.getvalue(), err.getvalue()


class RunTests(unittest.TestCase):
    def test_exit_code_and_output_pass_through_and_vm_is_removed(self):
        vm = FakeVM(result=types.SimpleNamespace(stdout="hi\n", stderr="warn\n", returncode=3))
        code, out, err = run_cli(vm, "run", "--", "echo", "hi")
        self.assertEqual((code, out, err), (3, "hi\n", "warn\n"))
        self.assertEqual(vm.argv, ["echo", "hi"])
        self.assertTrue(vm.cleaned)

    def test_timeout_returns_124_and_removes_vm(self):
        vm = FakeVM(error=subprocess.TimeoutExpired("ssh", 1))
        code, _, err = run_cli(vm, "run", "--timeout", "1", "--", "sleep", "9")
        self.assertEqual(code, 124)
        self.assertIn("did not finish", err)
        self.assertTrue(vm.cleaned)

    def test_failed_start_still_removes_vm(self):
        vm = FakeVM(start_error=RuntimeError("boom"))
        code, _, _ = run_cli(vm, "run", "--", "true")
        self.assertIn("boom", str(code))
        self.assertTrue(vm.cleaned)

    def test_ctrl_c_removes_vm(self):
        vm = FakeVM(error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            run_cli(vm, "run", "--", "sleep", "9")
        self.assertTrue(vm.cleaned)

    def test_arguments_are_not_joined_by_a_host_shell(self):
        vm = FakeVM(result=types.SimpleNamespace(stdout="", stderr="", returncode=0))
        run_cli(vm, "run", "--", "sh", "-c", "echo a; echo b")
        self.assertEqual(vm.argv, ["sh", "-c", "echo a; echo b"])

    def test_run_without_command_is_an_error(self):
        code, _, _ = run_cli(FakeVM(), "run")
        self.assertIn("give a command", str(code))


class RunPoolTests(unittest.TestCase):
    def run_pool(self, vm, lease_side_effect=None):
        with mock.patch.object(cli.poolmod, "lease", side_effect=lease_side_effect or (lambda *a, **k: "p-abc123")) as lease, \
                mock.patch.object(cli.poolmod, "spawn_refill") as spawn, \
                mock.patch.object(cli, "Registry"):
            result = run_cli(vm, "run", "--pool", "p", "--queue-timeout", "3", "--", "echo", "hi")
        return result, lease, spawn

    def test_pool_vm_is_destroyed_and_replacement_is_started(self):
        vm = FakeVM(result=types.SimpleNamespace(stdout="hi\n", stderr="", returncode=0))
        (code, out, _), lease, spawn = self.run_pool(vm)
        self.assertEqual((code, out), (0, "hi\n"))
        self.assertTrue(vm.cleaned)
        spawn.assert_called_once()
        self.assertEqual(lease.call_args[1]["queue_timeout"], 3)

    def test_failed_job_still_destroys_vm_and_asks_for_replacement(self):
        vm = FakeVM(error=subprocess.TimeoutExpired("ssh", 1))
        (code, _, _), _, spawn = self.run_pool(vm)
        self.assertEqual(code, 124)
        self.assertTrue(vm.cleaned)
        spawn.assert_called_once()

    def test_no_ready_vm_is_a_clear_error_and_nothing_is_cleaned(self):
        vm = FakeVM()
        (code, _, _), _, spawn = self.run_pool(vm, lease_side_effect=TimeoutError("no ready VM in pool 'p' after 3 s"))
        self.assertIn("no ready VM", str(code))
        self.assertFalse(vm.cleaned)
        spawn.assert_not_called()


class ParserTests(unittest.TestCase):
    def test_bad_name_is_rejected(self):
        from microheart.vm import MicroVM
        with self.assertRaises(ValueError):
            MicroVM("Bad Name", registry=mock.Mock())

    def test_version_flag(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as e:
                cli.main(["--version"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("microheart", out.getvalue())


if __name__ == "__main__":
    unittest.main()
