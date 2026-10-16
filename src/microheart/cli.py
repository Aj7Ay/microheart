"""Command line: microheart build-rootfs | fetch | up | ssh | status | console | down"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import assets
from .vm import MicroVM


def _paths():
    home = assets.cache_dir()
    return home / "alpine.ext4", home / "vm_key"


def _vm(a):
    rootfs, key = _paths()
    return MicroVM(a.rootfs or rootfs, a.key or key, vcpu=a.vcpu, mem_mib=a.mem)


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
    secs = _vm(a).start()
    print(f"VM is up ({secs:.1f} s). Try: sudo microheart ssh")


def cmd_ssh(a):
    vm = _vm(a)
    os.execvp("ssh", ["ssh", "-i", vm.key, "-o", "StrictHostKeyChecking=no",
                      "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                      "root@172.16.0.2", *a.command])


def cmd_status(a):
    vm = _vm(a)
    print(f"running (pid {vm.pid()})" if vm.running() else "stopped")


def cmd_console(a):
    print(_vm(a).tail(a.lines))


def cmd_down(a):
    _vm(a).clean()
    print("stopped; removed tap device and NAT rule")


def main(argv=None):
    p = argparse.ArgumentParser(prog="microheart")
    p.add_argument("--rootfs"); p.add_argument("--key")
    p.add_argument("--vcpu", type=int, default=1); p.add_argument("--mem", type=int, default=256)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download Firecracker and the kernel").set_defaults(f=cmd_fetch)
    b = sub.add_parser("build-rootfs", help="build the ext4 disk from the Dockerfile (needs Docker, root)")
    b.add_argument("--size", default="512M"); b.add_argument("--output", type=Path)
    b.set_defaults(f=cmd_build)
    sub.add_parser("up", help="boot the VM").set_defaults(f=cmd_up)
    s = sub.add_parser("ssh", help="log in to the guest"); s.add_argument("command", nargs="*")
    s.set_defaults(f=cmd_ssh)
    sub.add_parser("status").set_defaults(f=cmd_status)
    c = sub.add_parser("console"); c.add_argument("-n", "--lines", type=int, default=40)
    c.set_defaults(f=cmd_console)
    sub.add_parser("down", help="stop the VM and clean the network").set_defaults(f=cmd_down)
    a = p.parse_args(argv)
    try:
        a.f(a)
    except (PermissionError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
