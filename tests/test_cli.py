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
