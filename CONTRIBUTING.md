# Contributing

Thanks for your help. This is a small project. Keep changes small and clear.

## Set up

    git clone https://github.com/Aj7Ay/microheart && cd microheart
    python3 -m venv .venv && . .venv/bin/activate
    pip install -e . build

## Rules

- Standard library only. Do not add a Python dependency without a strong reason.
- Run the tests: `PYTHONPATH=src python -m unittest discover -s tests`.
- Test on a real Linux host with `/dev/kvm` and paste the output in your pull request.
- Keep the guest recipe in `src/microheart/data/` small. No passwords or keys in the image.
- Write simple English in docs and comments.

## Build

    python -m build        # pure wheel
    python scripts/bundle.py && python -m build --wheel   # wheel with Firecracker + kernel (x86_64 Linux)
