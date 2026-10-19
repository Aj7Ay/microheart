"""Warm pool: N booted, ready VMs. One job per VM; the VM is destroyed after the job and replaced.

There is no daemon. `run --pool` takes a ready VM, runs the command, destroys the VM and starts a
detached `microheart pool refill`. The registry (SQLite) makes taking a VM and reserving new VMs atomic.
"""
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import assets
from .state import Registry
from .vm import MicroVM

BOOT_GRACE = 120      # seconds a 'booting' VM may take before it counts as stale


def reap(registry, pool: str) -> list:
    """Remove pool VMs whose Firecracker process is gone (crash, killed). Return their names."""
    now, gone = time.time(), []
    for rec in registry.vms_in_pool(pool):
        vm = MicroVM(rec["name"], registry=registry)
        dead = not vm.running()
        stale = dead and (rec["state"] in ("ready", "leased") or now - rec["created"] > BOOT_GRACE)
        if stale:
            vm.clean()
            gone.append(rec["name"])
    return gone


def refill(registry, pool: str, rootfs, key, workers=4, wait=60) -> list:
    """Boot VMs until the pool has its size again. Return [(name, error or None), ...]."""
    reap(registry, pool)
    cfg = registry.pool_get(pool)
    if cfg is None:
        raise RuntimeError(f"no pool named {pool!r}")
    names = registry.reserve(pool)

    def boot(name):
        try:
            reg = Registry(registry.path)           # one SQLite connection per thread
            try:
                MicroVM(name, rootfs, key, vcpu=cfg["vcpu"], mem_mib=cfg["mem"], registry=reg).start(
                    wait=wait, reserved=True)
            finally:
                reg.close()
            return name, None
        except Exception as e:                      # start() already removed the failed VM
            return name, str(e).splitlines()[0] if str(e) else type(e).__name__

    if not names:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(names))) as ex:
        return list(ex.map(boot, names))


def spawn_refill(pool: str, rootfs, key) -> None:
    """Start `microheart pool refill` in the background, detached from this process."""
    with open(assets.cache_dir() / "pool-refill.log", "ab") as log:
        subprocess.Popen([sys.executable, "-m", "microheart", "--rootfs", str(rootfs), "--key", str(key),
                          "pool", "refill", pool], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         start_new_session=True)


def lease(registry, pool: str, rootfs, key, queue_timeout=30, poll=0.5) -> str:
    """Return the name of a ready VM that now belongs to the caller. Wait up to queue_timeout seconds."""
    if registry.pool_get(pool) is None:
        raise RuntimeError(f"no pool named {pool!r}")
    deadline, asked = time.time() + queue_timeout, False
    while True:
        name = registry.lease(pool)
        if name:
            vm = MicroVM(name, registry=registry)
            if vm.running():
                return name
            vm.clean()                              # a ready VM that died: drop it, try the next
            continue
        if not asked:
            spawn_refill(pool, rootfs, key)         # nothing ready: make sure the pool is filling
            asked = True
        if time.time() >= deadline:
            raise TimeoutError(f"no ready VM in pool {pool!r} after {queue_timeout} s")
        time.sleep(poll)


def scale(registry, pool: str, size: int, rootfs, key) -> list:
    """Change the size. Growing boots VMs. Shrinking destroys surplus ready VMs."""
    registry.pool_set_size(pool, size)
    ready = [r for r in registry.vms_in_pool(pool) if r["state"] == "ready"]
    live = len(ready) + registry.counts(pool)["booting"]
    for rec in ready[: max(0, live - size)]:
        MicroVM(rec["name"], registry=registry).clean()
    return refill(registry, pool, rootfs, key)


def delete(registry, pool: str) -> int:
    """Destroy every VM of the pool (also leased ones) and remove the pool. Return the VM count."""
    registry.pool_delete(pool)                       # first: so no refill makes new VMs
    recs = registry.vms_in_pool(pool)
    for rec in recs:
        MicroVM(rec["name"], registry=registry).clean()
    return len(recs)
