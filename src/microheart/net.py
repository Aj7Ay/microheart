"""Host network: one TAP device and one NAT rule. Needs root."""
import json
import subprocess


def _run(*cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.DEVNULL if not check else None)


def host_iface() -> str:
    out = _run("ip", "-j", "route", "list", "default", capture=True).stdout
    return json.loads(out)[0]["dev"]


def up(tap: str, host_ip: str) -> str:
    if _run("ip", "link", "show", tap, check=False).returncode != 0:
        _run("ip", "tuntap", "add", "dev", tap, "mode", "tap")
    if f"{host_ip}/30" not in _run("ip", "addr", "show", "dev", tap, capture=True).stdout:
        _run("ip", "addr", "add", f"{host_ip}/30", "dev", tap)
    _run("ip", "link", "set", "dev", tap, "up")
    _run("sysctl", "-q", "-w", "net.ipv4.ip_forward=1")
    _run("iptables", "-P", "FORWARD", "ACCEPT")
    iface = host_iface()
    if _run("iptables", "-t", "nat", "-C", "POSTROUTING", "-o", iface, "-j", "MASQUERADE",
            check=False).returncode != 0:
        _run("iptables", "-t", "nat", "-A", "POSTROUTING", "-o", iface, "-j", "MASQUERADE")
    return iface


def down(tap: str) -> None:
    _run("ip", "link", "del", tap, check=False)
    try:
        iface = host_iface()
    except (IndexError, subprocess.CalledProcessError):
        return
    _run("iptables", "-t", "nat", "-D", "POSTROUTING", "-o", iface, "-j", "MASQUERADE", check=False)
