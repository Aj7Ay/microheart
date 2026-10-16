"""MicroVM: build a config file, boot Firecracker, reach the guest over SSH."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from . import api, assets, net

GUEST_IP = "172.16.0.2"   # fixed in the rootfs: data/files/etc/network/interfaces
HOST_IP = "172.16.0.1"
GUEST_MAC = "06:00:AC:10:00:02"


class MicroVM:
    def __init__(self, rootfs, key, vcpu=1, mem_mib=256, tap="tap0", run_dir=None):
        self.rootfs = str(Path(rootfs).resolve())
        self.key = str(Path(key).resolve())
        self.vcpu, self.mem, self.tap = vcpu, mem_mib, tap
        self.run_dir = Path(run_dir or assets.cache_dir() / "run")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.sock = str(self.run_dir / "firecracker.socket")
        self.pidfile = self.run_dir / "firecracker.pid"
        self.console = self.run_dir / "console.log"

    # -- state ---------------------------------------------------------
    def pid(self):
        try:
            pid = int(self.pidfile.read_text())
            os.kill(pid, 0)
            return pid
        except (FileNotFoundError, ValueError, ProcessLookupError):
            return None

    def running(self) -> bool:
        return self.pid() is not None

    # -- lifecycle -----------------------------------------------------
    def config(self) -> dict:
        return {
            "boot-source": {"kernel_image_path": str(assets.kernel_path()),
                            "boot_args": "console=ttyS0 reboot=k panic=1"},
            "drives": [{"drive_id": "rootfs", "path_on_host": self.rootfs,
                        "is_root_device": True, "is_read_only": False}],
            "network-interfaces": [{"iface_id": "net1", "guest_mac": GUEST_MAC,
                                    "host_dev_name": self.tap}],
            "machine-config": {"vcpu_count": self.vcpu, "mem_size_mib": self.mem},
        }

    def start(self, wait=60):
        if os.geteuid() != 0:
            raise PermissionError("run as root (use sudo)")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise PermissionError("no access to /dev/kvm")
        if self.running():
            return
        fc = assets.firecracker_path()
        net.up(self.tap, HOST_IP)
        cfg = self.run_dir / "vm_config.json"
        cfg.write_text(json.dumps(self.config(), indent=2))
        Path(self.sock).unlink(missing_ok=True)
        with open(self.console, "w") as log:
            proc = subprocess.Popen([str(fc), "--api-sock", self.sock, "--config-file", str(cfg),
                                     "--enable-pci"], stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        self.pidfile.write_text(str(proc.pid))
        t0 = time.time()
        while time.time() - t0 < wait:
            if proc.poll() is not None:
                raise RuntimeError("Firecracker stopped:\n" + self.tail())
            if self.ssh("true", check=False).returncode == 0:
                return time.time() - t0
            time.sleep(1)
        raise TimeoutError(f"no SSH after {wait} s:\n" + self.tail())

    def stop(self):
        pid = self.pid()
        if pid:
            self.ssh("reboot", check=False)       # a guest reboot makes Firecracker exit
            for _ in range(10):
                if not self.running():
                    break
                time.sleep(1)
            if self.running():
                os.kill(pid, signal.SIGTERM)
        self.pidfile.unlink(missing_ok=True)
        Path(self.sock).unlink(missing_ok=True)

    def clean(self):
        self.stop()
        net.down(self.tap)

    # -- guest access --------------------------------------------------
    def ssh(self, command: str, check=True, timeout=30):
        return subprocess.run(
            ["ssh", "-i", self.key, "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
             "-o", "ConnectTimeout=3", f"root@{GUEST_IP}", command],
            check=check, text=True, capture_output=True, timeout=timeout)

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
