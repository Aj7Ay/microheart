"""Command line: microheart build-rootfs | fetch | up | list | ssh | run | status | console | down"""
import argparse
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

from . import __version__, assets
from .state import Registry
from .vm import MicroVM


def _paths():
    home = assets.cache_dir()
    return home / "alpine.ext4", home / "vm_key"


def _vm(a, name=None):
    rootfs, key = _paths()
    return MicroVM(name or a.name, a.rootfs or rootfs, a.key or key, vcpu=a.vcpu, mem_mib=a.mem)


def cmd_fetch(a):
    print("firecracker:", assets.firecracker_path())
    print("kernel:     ", assets.kernel_path())


def cmd_build(a):
    rootfs, key = _paths()
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-f", str(key), "-N", ""], check=True)
    script = assets.recipe_dir() / "build-rootfs.sh"
    subprocess.run(["bash", str(script), f"{key}.pub", a.size, str(a.output or rootfs)], check=True)


def cmd_up(a):
    vm = _vm(a)
    secs = vm.start()
    if secs is None:
        print(f"VM {a.name!r} already runs ({vm.guest_ip}).")
    else:
        print(f"VM {a.name!r} is up ({secs:.1f} s, {vm.guest_ip}). Try: microheart ssh --name {a.name}")


def cmd_list(a):
    reg = Registry()
    rows = reg.list()
    if not rows:
        print("no VMs")
        return
    print(f"{'NAME':<20}{'STATE':<10}{'PID':<9}ADDRESS")
    for r in rows:
        vm = MicroVM(r["name"], registry=reg)
        state = "running" if vm.running() else "dead"
        print(f"{r['name']:<20}{state:<10}{str(r['pid'] or '-'):<9}{vm.guest_ip}")


def cmd_ssh(a):
    vm = _vm(a)
    os.execvp("ssh", vm.ssh_argv(" ".join(a.command) if a.command else None))


def cmd_run(a):
    command = [c for i, c in enumerate(a.command) if not (i == 0 and c == "--")]
    if not command:
        sys.exit("ERROR: give a command, for example: microheart run -- uname -a")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    vm = _vm(a, a.name if a.name != "default" else f"run-{secrets.token_hex(3)}")
    try:
        vm.start()
        r = vm.run(command, timeout=a.timeout)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(f"ERROR: command did not finish in {a.timeout} s", file=sys.stderr)
        return 124
    finally:
        vm.clean()


def cmd_status(a):
    vm = _vm(a)
    if not vm.rec:
        print("no such VM")
    elif vm.running():
        print(f"running (pid {vm.pid()}, {vm.guest_ip})")
    else:
        print("dead (stale record: run 'microheart down')")


def cmd_console(a):
    print(_vm(a).tail(a.lines))


def cmd_down(a):
    names = [r["name"] for r in Registry().list()] if a.all else [a.name]
    for n in names:
        _vm(a, n).clean()
        print(f"stopped {n!r}; removed its disk copy and network device")


def main(argv=None):
    p = argparse.ArgumentParser(prog="microheart")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--rootfs", help="base disk (default: the one from build-rootfs)")
    p.add_argument("--key", help="SSH private key (default: the one from build-rootfs)")
    p.add_argument("--vcpu", type=int, default=1)
    p.add_argument("--mem", type=int, default=256, help="guest memory in MiB")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, f, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(f=f)
        return sp

    def named(sp):
        sp.add_argument("--name", default="default", help="VM name (default: default)")
        return sp

    add("fetch", cmd_fetch, "download Firecracker and the kernel")
    b = add("build-rootfs", cmd_build, "build the ext4 disk from the Dockerfile (needs Docker, root)")
    b.add_argument("--size", default="512M")
    b.add_argument("--output", type=Path)
    named(add("up", cmd_up, "boot a VM"))
    add("list", cmd_list, "list VMs")
    s = named(add("ssh", cmd_ssh, "log in to a VM, or run one command"))
    s.add_argument("command", nargs="*")
    r = named(add("run", cmd_run, "boot a temporary VM, run a command, remove the VM"))
    r.add_argument("--timeout", type=int, default=60, help="seconds for the command (default 60)")
    r.add_argument("command", nargs=argparse.REMAINDER)
    named(add("status", cmd_status, "show if a VM runs"))
    c = named(add("console", cmd_console, "show the last console lines of a VM"))
    c.add_argument("-n", "--lines", type=int, default=40)
    d = named(add("down", cmd_down, "stop a VM and remove its disk copy and network device"))
    d.add_argument("--all", action="store_true", help="stop every VM")
    a = p.parse_args(argv)
    try:
        sys.exit(a.f(a) or 0)
    except (PermissionError, RuntimeError, TimeoutError, ValueError, subprocess.CalledProcessError) as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
