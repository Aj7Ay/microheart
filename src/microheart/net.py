"""Host network: one TAP device per VM and one shared NAT rule. Needs root.

Changes run under a file lock, so VMs that start or stop in parallel do not race on the shared NAT rule.
"""
import fcntl
import json
import subprocess
from contextlib import contextmanager

from . import assets


@contextmanager
def _locked():
    with open(assets.cache_dir() / "net.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _run(*cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.DEVNULL if not check else None)


def host_iface() -> str:
    out = _run("ip", "-j", "route", "list", "default", capture=True).stdout
    return json.loads(out)[0]["dev"]


def up(tap: str, host_ip: str) -> str:
    with _locked():
        if _run("ip", "link", "show", tap, check=False).returncode != 0:
            _run("ip", "tuntap", "add", "dev", tap, "mode", "tap")
        if f"{host_ip}/30" not in _run("ip", "addr", "show", "dev", tap, capture=True).stdout:
            _run("ip", "addr", "add", f"{host_ip}/30", "dev", tap)
        _run("ip", "link", "set", "dev", tap, "up")
        _run("sysctl", "-q", "-w", "net.ipv4.ip_forward=1")
        _run("iptables", "-w", "-P", "FORWARD", "ACCEPT")
        iface = host_iface()
        if _run("iptables", "-w", "-t", "nat", "-C", "POSTROUTING", "-o", iface, "-j", "MASQUERADE",
                check=False).returncode != 0:
            _run("iptables", "-w", "-t", "nat", "-A", "POSTROUTING", "-o", iface, "-j", "MASQUERADE")
        return iface


def down(tap: str, remove_nat=True) -> None:
    """Remove the TAP device. Remove the shared NAT rule only if remove_nat says so.

    remove_nat is a bool, or a function that is called inside the lock. A function lets the caller
    check "is another VM still registered?" at the moment when no other VM can change the network.
    """
    with _locked():
        _run("ip", "link", "del", tap, check=False)
        if callable(remove_nat):
            remove_nat = remove_nat()
        if not remove_nat:
            return
        try:
            iface = host_iface()
        except (IndexError, subprocess.CalledProcessError):
            return
        _run("iptables", "-w", "-t", "nat", "-D", "POSTROUTING", "-o", iface, "-j", "MASQUERADE", check=False)
