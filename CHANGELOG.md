# Changelog

## Unreleased

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
