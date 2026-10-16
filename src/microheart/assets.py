"""Find the Firecracker binary and the guest kernel.

Order: files bundled in the wheel (microheart/bin), then the cache folder.
If neither exists, download them into the cache folder.
"""
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path

S3 = "https://s3.amazonaws.com/spec.ccfc.min"
RELEASES = "https://github.com/firecracker-microvm/firecracker/releases"
PKG = Path(__file__).parent


def cache_dir() -> Path:
    base = os.environ.get("MICROHEART_HOME") or os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "microheart")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _save(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _find(name_glob: str):
    for d in (PKG / "bin", cache_dir()):
        hits = sorted(d.glob(name_glob)) if d.is_dir() else []
        if hits:
            return hits[-1]
    return None


def firecracker_path() -> Path:
    found = _find("firecracker")
    if found:
        return found
    arch = platform.machine()
    latest_url = urllib.request.urlopen(f"{RELEASES}/latest", timeout=60).geturl()
    tag = latest_url.rstrip("/").split("/")[-1]
    dest = cache_dir() / "firecracker"
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "fc.tgz"
        _save(f"{RELEASES}/download/{tag}/firecracker-{tag}-{arch}.tgz", tgz)
        with tarfile.open(tgz) as t:
            t.extractall(tmp, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(tmp)
        src = Path(tmp) / f"release-{tag}-{arch}" / f"firecracker-{tag}-{arch}"
        shutil.copy(src, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def kernel_path() -> Path:
    found = _find("vmlinux-*")
    if found:
        return found
    arch = platform.machine()
    top = _get(f"{S3}?list-type=2&prefix=firecracker-ci/&delimiter=/").decode()
    prefixes = re.findall(r"<Prefix>(firecracker-ci/[0-9]{8}-[^/]+/)</Prefix>", top)
    prefix = sorted(prefixes)[-1]
    listing = _get(f"{S3}?list-type=2&prefix={prefix}{arch}/vmlinux-").decode()
    keys = re.findall(rf"<Key>({re.escape(prefix)}{arch}/vmlinux-\d+\.\d+\.\d{{1,3}})</Key>", listing)
    key = sorted(keys, key=lambda k: [int(x) for x in re.findall(r"\d+", k.rsplit("vmlinux-", 1)[1])])[-1]
    dest = cache_dir() / key.rsplit("/", 1)[1]
    _save(f"{S3}/{key}", dest)
    return dest


def recipe_dir() -> Path:
    """Folder with the Dockerfile and build-rootfs.sh."""
    return PKG / "data"
