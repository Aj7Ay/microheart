"""MicroVM: one named Firecracker VM with its own disk copy, TAP device and address."""
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import api, assets, net
from .state import Registry, addresses, guest_mac, tap_name, validate_name


def _clone(src: str, dst: Path) -> None:
    """Copy the base disk. Use a copy-on-write copy when the file system can do it."""
    try:
        subprocess.run(["cp", "--reflink=auto", "--sparse=always", src, str(dst)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.copyfile(src, dst)


class MicroVM:
    def __init__(self, name="default", rootfs=None, key=None, vcpu=1, mem_mib=256, registry=None, run_dir=None):
        self.name = validate_name(name)
        self.base_rootfs = str(Path(rootfs).resolve()) if rootfs else None
        self.key = str(Path(key).resolve()) if key else None
        self.vcpu, self.mem = vcpu, mem_mib
        self.registry = registry or Registry()
        self.dir = Path(run_dir or assets.cache_dir()) / "vms" / name
        self.sock = str(self.dir / "firecracker.socket")
        self.console = self.dir / "console.log"

    # -- identity ------------------------------------------------------
    @property
    def rec(self):
        return self.registry.get(self.name)

    def _need_rec(self) -> dict:
        rec = self.rec
        if not rec:
            raise RuntimeError(f"no VM named {self.name!r}")
        return rec

    @property
    def host_ip(self) -> str:
        return addresses(self._need_rec()["idx"])[0]

    @property
    def guest_ip(self) -> str:
        return addresses(self._need_rec()["idx"])[1]

    @property
    def tap(self) -> str:
        return tap_name(self._need_rec()["idx"])

    # -- state ---------------------------------------------------------
    def pid(self):
        rec = self.rec
        pid = rec and rec["pid"]
        if not pid:
            return None
        try:
            os.kill(pid, 0)
            return pid
        except ProcessLookupError:
            return None

    def running(self) -> bool:
        return self.pid() is not None

    # -- lifecycle -----------------------------------------------------
    def config(self, disk: Path) -> dict:
        rec = self._need_rec()
        host, guest = addresses(rec["idx"])
        args = (f"console=ttyS0 reboot=k panic=1 "
                f"microheart.ip={guest}/30 microheart.gw={host} microheart.name={self.name}")
        return {
            "boot-source": {"kernel_image_path": str(assets.kernel_path()), "boot_args": args},
            "drives": [{"drive_id": "rootfs", "path_on_host": str(disk),
                        "is_root_device": True, "is_read_only": False}],
            "network-interfaces": [{"iface_id": "net1", "guest_mac": guest_mac(rec["idx"]),
                                    "host_dev_name": tap_name(rec["idx"])}],
            "machine-config": {"vcpu_count": self.vcpu, "mem_size_mib": self.mem},
        }

    def start(self, wait=60, reserved=False):
        """Boot the VM. Return the seconds until SSH worked, or None when it already runs.

        reserved=True: the registry record exists already (a pool VM that the pool reserved).
        """
        if os.geteuid() != 0:
            raise PermissionError("run as root (use sudo)")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise PermissionError("no access to /dev/kvm")
        if not self.base_rootfs or not self.key:
            raise RuntimeError("a base disk and an SSH key are needed (run: microheart build-rootfs)")
        fc = assets.firecracker_path()
        if reserved:
            if not self.rec:
                raise RuntimeError(f"no reserved record for VM {self.name!r}")
        else:
            if self.rec:
                if self.running():
                    return None
                self.clean()                   # stale record from a crash
            self.registry.create(self.name)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            disk = self.dir / "rootfs.ext4"
            _clone(self.base_rootfs, disk)
            net.up(self.tap, self.host_ip)
            cfg = self.dir / "vm_config.json"
            cfg.write_text(json.dumps(self.config(disk), indent=2))
            with open(self.console, "w") as log:
                proc = subprocess.Popen([str(fc), "--api-sock", self.sock, "--config-file", str(cfg),
                                         "--enable-pci"], stdout=log, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
            self.registry.set_pid(self.name, proc.pid)
            t0 = time.time()
            while time.time() - t0 < wait:
                if proc.poll() is not None:
                    raise RuntimeError("Firecracker stopped:\n" + self.tail())
                if self.ssh("true", check=False).returncode == 0:
                    self.registry.set_state(self.name, "ready" if self.rec["pool"] else "running")
                    return time.time() - t0
                time.sleep(1)
            raise TimeoutError(f"no SSH after {wait} s:\n" + self.tail())
        except BaseException:
            tail = self.tail()
            self.clean()
            if tail:
                print(tail)
            raise

    def stop(self):
        pid = self.pid()
        if pid:
            try:
                self.ssh("reboot", check=False, timeout=10)    # a guest reboot makes Firecracker exit
            except subprocess.TimeoutExpired:
                pass
            for _ in range(10):
                if not self.running():
                    break
                time.sleep(1)
            if self.running():
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
            if self.running():
                os.kill(pid, signal.SIGKILL)
        if self.rec:
            self.registry.set_pid(self.name, None)

    def clean(self):
        """Stop the VM, remove its TAP device, disk copy and record."""
        self.stop()
        rec = self.rec
        if rec:
            def last_vm():       # called inside the network lock
                return not [v for v in self.registry.list() if v["name"] != self.name]
            net.down(tap_name(rec["idx"]), remove_nat=last_vm)
        shutil.rmtree(self.dir, ignore_errors=True)
        self.registry.delete(self.name)

    # -- guest access --------------------------------------------------
    def ssh_argv(self, command=None):
        argv = ["ssh", "-i", self.key, "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=3", f"root@{self.guest_ip}"]
        return argv + ([command] if command else [])

    def ssh(self, command: str, check=True, timeout=30):
        return subprocess.run(self.ssh_argv(command), check=check, text=True,
                              capture_output=True, timeout=timeout)

    def run(self, argv, timeout=60):
        """Run a command in the guest. The arguments are quoted, so the host shell never sees them."""
        return self.ssh(shlex.join(argv), check=False, timeout=timeout)

    def machine_config(self):
        return api.request(self.sock, "GET", "/machine-config")

    def tail(self, n=30) -> str:
        try:
            return "\n".join(self.console.read_text().splitlines()[-n:])
        except FileNotFoundError:
            return ""

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.clean()
