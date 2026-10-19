"""Command line: build-rootfs | fetch | up | list | ssh | run | status | console | down | pool | benchmark"""
import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, assets, bench, pool as poolmod
from .state import Registry
from .vm import MicroVM


def _paths():
    home = assets.cache_dir()
    return home / "alpine.ext4", home / "vm_key"


def _disk_and_key(a):
    rootfs, key = _paths()
    return a.rootfs or rootfs, a.key or key


def _vm(a, name=None):
    rootfs, key = _disk_and_key(a)
    return MicroVM(name or a.name, rootfs, key, vcpu=a.vcpu, mem_mib=a.mem)


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
    print(f"{'NAME':<24}{'POOL':<14}{'STATE':<10}{'PID':<9}ADDRESS")
    for r in rows:
        vm = MicroVM(r["name"], registry=reg)
        state = r["state"] if vm.running() else ("booting" if r["state"] == "booting" and not r["pid"] else "dead")
        print(f"{r['name']:<24}{(r['pool'] or '-'):<14}{state:<10}{str(r['pid'] or '-'):<9}{vm.guest_ip}")


def cmd_ssh(a):
    vm = _vm(a)
    os.execvp("ssh", vm.ssh_argv(" ".join(a.command) if a.command else None))


def _run_in(vm, command, timeout):
    """Run a command in a VM, print its output, return the exit code."""
    try:
        r = vm.run(command, timeout=timeout)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(f"ERROR: command did not finish in {timeout} s", file=sys.stderr)
        return 124


def cmd_run(a):
    command = [c for i, c in enumerate(a.command) if not (i == 0 and c == "--")]
    if not command:
        sys.exit("ERROR: give a command, for example: microheart run -- uname -a")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if a.pool:
        rootfs, key = _disk_and_key(a)
        name = poolmod.lease(Registry(), a.pool, rootfs, key, queue_timeout=a.queue_timeout)
        vm = _vm(a, name)
        try:
            return _run_in(vm, command, a.timeout)
        finally:
            vm.clean()                                  # one job per VM: destroy it ...
            poolmod.spawn_refill(a.pool, rootfs, key)   # ... and boot a replacement
    vm = _vm(a, a.name if a.name != "default" else f"run-{secrets.token_hex(3)}")
    try:
        vm.start()
        return _run_in(vm, command, a.timeout)
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


# -- pool ---------------------------------------------------------------
def _print_boot_results(results):
    for name, err in results:
        print(f"  {name}: {'ready' if err is None else 'FAILED: ' + err}")


def cmd_pool_create(a):
    reg = Registry()
    reg.pool_create(a.pool_name, a.size, a.pool_vcpu, a.pool_mem)
    rootfs, key = _disk_and_key(a)
    print(f"pool {a.pool_name!r}: booting {a.size} VMs ...")
    t0 = time.time()
    _print_boot_results(poolmod.refill(reg, a.pool_name, rootfs, key))
    print(f"done in {time.time() - t0:.1f} s. Try: microheart run --pool {a.pool_name} -- uname -a")


def cmd_pool_refill(a):
    rootfs, key = _disk_and_key(a)
    _print_boot_results(poolmod.refill(Registry(), a.pool_name, rootfs, key))


def cmd_pool_status(a):
    reg = Registry()
    pools = [p for p in reg.pools() if not a.pool_name or p["name"] == a.pool_name]
    if not pools:
        print("no pools")
        return
    print(f"{'POOL':<22}{'SIZE':<6}{'READY':<7}{'BOOTING':<9}{'LEASED':<8}VM")
    for p in pools:
        c = reg.counts(p["name"])
        print(f"{p['name']:<22}{p['size']:<6}{c['ready']:<7}{c['booting']:<9}{c['leased']:<8}"
              f"{p['vcpu']} vCPU, {p['mem']} MiB")


def cmd_pool_scale(a):
    rootfs, key = _disk_and_key(a)
    _print_boot_results(poolmod.scale(Registry(), a.pool_name, a.size, rootfs, key))


def cmd_pool_delete(a):
    print(f"pool {a.pool_name!r} deleted; {poolmod.delete(Registry(), a.pool_name)} VMs removed")


def cmd_benchmark(a):
    reg, (rootfs, key) = Registry(), _disk_and_key(a)
    cold = []
    for _ in range(a.count):
        vm = _vm(a, f"bench-{secrets.token_hex(3)}")
        t0 = time.perf_counter()
        try:
            vm.start()
            vm.run(["true"], timeout=30)
            cold.append(time.perf_counter() - t0)
        finally:
            vm.clean()
    print(bench.summary("cold: boot + command + result", cold))
    if not a.pool:
        return
    warm = []
    for _ in range(a.count):
        deadline = time.time() + 120               # wait outside the timing until the pool is full again
        while reg.counts(a.pool)["ready"] < 1 and time.time() < deadline:
            time.sleep(0.5)
        t0 = time.perf_counter()
        name = poolmod.lease(reg, a.pool, rootfs, key, queue_timeout=5)
        vm = _vm(a, name)
        try:
            vm.run(["true"], timeout=30)
            warm.append(time.perf_counter() - t0)
        finally:
            vm.clean()
            poolmod.spawn_refill(a.pool, rootfs, key)
    print(bench.summary("warm: lease + command + result", warm))
    print(f"warm p50 is {bench.percentile(cold, 50) / bench.percentile(warm, 50):.1f}x faster than cold p50")


def main(argv=None):
    p = argparse.ArgumentParser(prog="microheart")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--rootfs", help="base disk (default: the one from build-rootfs)")
    p.add_argument("--key", help="SSH private key (default: the one from build-rootfs)")
    p.add_argument("--vcpu", type=int, default=1)
    p.add_argument("--mem", type=int, default=256, help="guest memory in MiB")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(parent, name, f, help_):
        sp = parent.add_parser(name, help=help_)
        sp.set_defaults(f=f)
        return sp

    def named(sp):
        sp.add_argument("--name", default="default", help="VM name (default: default)")
        return sp

    add(sub, "fetch", cmd_fetch, "download Firecracker and the kernel")
    b = add(sub, "build-rootfs", cmd_build, "build the ext4 disk from the Dockerfile (needs Docker, root)")
    b.add_argument("--size", default="512M")
    b.add_argument("--output", type=Path)
    named(add(sub, "up", cmd_up, "boot a VM"))
    add(sub, "list", cmd_list, "list VMs")
    s = named(add(sub, "ssh", cmd_ssh, "log in to a VM, or run one command"))
    s.add_argument("command", nargs="*")
    r = named(add(sub, "run", cmd_run, "run a command in a temporary VM (or a pool VM), then remove the VM"))
    r.add_argument("--pool", help="take a ready VM from this pool instead of booting a new one")
    r.add_argument("--queue-timeout", type=int, default=30, help="seconds to wait for a ready pool VM (default 30)")
    r.add_argument("--timeout", type=int, default=60, help="seconds for the command (default 60)")
    r.add_argument("command", nargs=argparse.REMAINDER)
    named(add(sub, "status", cmd_status, "show if a VM runs"))
    c = named(add(sub, "console", cmd_console, "show the last console lines of a VM"))
    c.add_argument("-n", "--lines", type=int, default=40)
    d = named(add(sub, "down", cmd_down, "stop a VM and remove its disk copy and network device"))
    d.add_argument("--all", action="store_true", help="stop every VM")

    pp = sub.add_parser("pool", help="warm pools of ready VMs").add_subparsers(dest="pool_cmd", required=True)
    pc = add(pp, "create", cmd_pool_create, "create a pool and boot its VMs")
    pc.add_argument("pool_name")
    pc.add_argument("--size", type=int, default=3)
    pc.add_argument("--vcpu", dest="pool_vcpu", type=int, default=1)
    pc.add_argument("--mem", dest="pool_mem", type=int, default=256, help="guest memory in MiB")
    add(pp, "status", cmd_pool_status, "show pools").add_argument("pool_name", nargs="?")
    ps = add(pp, "scale", cmd_pool_scale, "change the size of a pool")
    ps.add_argument("pool_name")
    ps.add_argument("--size", type=int, required=True)
    add(pp, "refill", cmd_pool_refill, "boot VMs until the pool is full (run in the background by 'run --pool')"
        ).add_argument("pool_name")
    add(pp, "delete", cmd_pool_delete, "remove a pool and all its VMs").add_argument("pool_name")

    bm = add(sub, "benchmark", cmd_benchmark, "measure cold start (and warm pool dispatch with --pool)")
    bm.add_argument("--count", type=int, default=5)
    bm.add_argument("--pool", help="also measure this pool (it needs at least one ready VM)")
    a = p.parse_args(argv)
    try:
        sys.exit(a.f(a) or 0)
    except (PermissionError, RuntimeError, TimeoutError, ValueError, subprocess.CalledProcessError) as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
