# Changelog

## 0.2.0a1 (pre-release: not tested on a real host yet)

Install with `pip install --pre microheart`. Plain `pip install microheart` still gives 0.1.2.

- Several VMs at once: `--name`, `list`, `down --all`. Each VM gets its own disk copy, `/30` network, TAP device and MAC.
- State in a small SQLite registry (standard library). Stale records from a crash are cleaned on the next `up`.
- `microheart run -- command`: boot a temporary VM, run the command, return its output and exit code, remove the VM.
- The address goes to the guest on the kernel command line. One disk image works for every VM.
  **Rebuild the disk** (`microheart build-rootfs`) to use more than one VM. An old 0.1.x disk still works for the first VM.
- The shared NAT rule is removed only when the last VM goes down.
- Unit tests (`python -m unittest discover -s tests`), run in CI.

## 0.1.2

- `microheart --version`, and `python -m microheart`.
- README: install with pipx so the `microheart` command is on the PATH.

## 0.1.1

First version tested on a real host (Ubuntu 24.04, AWS c8i.large with nested virtualization).
Tested: install, fetch, build-rootfs, up (SSH ready in about 3 s), ssh, internet from the guest, down.

- Fix: `build-rootfs` works without buildx (Ubuntu's `docker.io` has none). It uses `docker create` + `docker export`.
- Fix: remove `/.dockerenv` from the disk. OpenRC thought it ran in Docker and skipped the hostname and
  networking services, so SSH never started.
- Security: remove the passwordless root console login.
- `status` and `console` now show in `--help`.

## 0.1.0 (unreleased)

- First version. Alpha: not yet tested on a real host.
- `MicroVM` class and `microheart` command: `fetch`, `build-rootfs`, `up`, `ssh`, `status`, `console`, `down`.
- Zero Python dependencies (standard library only).
- Alpine + OpenRC root file system recipe (`Dockerfile`, `build-rootfs.sh`).
