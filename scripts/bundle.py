"""Put the Firecracker binary and kernel inside the package before building a wheel.

    python scripts/bundle.py && python -m build --wheel
Run on x86_64 Linux (the files are for that platform). Then retag the wheel:
    wheel tags --platform-tag manylinux_2_17_x86_64 --remove dist/*.whl
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from microheart import assets  # noqa: E402

dest = Path(__file__).parent.parent / "src" / "microheart" / "bin"
dest.mkdir(exist_ok=True)
for p in (assets.firecracker_path(), assets.kernel_path()):
    shutil.copy(p, dest / p.name)
    print("bundled", p.name)
