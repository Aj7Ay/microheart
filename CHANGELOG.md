# Changelog

## 0.3.1

First release tested on a real host with the multi-VM, `run` and pool features (DigitalOcean droplet, Ubuntu 24.04).

- Fix: `pool delete` (and `pool scale` to a smaller size) crashed with `TypeError` when it stopped a running VM, because
  stopping tried to use SSH without a key. Stopping a VM no longer needs SSH: with a key the guest is asked to reboot,
  without a key the process is stopped directly (SIGTERM, then SIGKILL). A regression test covers it.
- `ssh_argv` gives a clear error when no key was given.

## 0.3.0 (alpha: multi-VM, run and the pool are not tested on a real host yet)

- **Warm pool.** `microheart pool create NAME --size N` boots N ready VMs. `microheart run --pool NAME -- cmd`
  takes one ready VM, runs the command, **destroys the VM** and starts a background refill. One job per VM,
  so the next job never sees files or processes of the last one.
- `pool status`, `pool scale`, `pool delete`, and `pool refill` (used by `run --pool`; no daemon).
- Atomic leases and atomic refills (SQLite transactions): two jobs never get the same VM, and parallel refills never
  boot more VMs than the pool size. A job waits at most `--queue-timeout` seconds, then gets a clear error.
- Pool VMs whose Firecracker process died are removed (`reap`) and replaced on the next refill.
- `microheart benchmark --count N [--pool NAME]`: cold start and warm dispatch, with min, p50, p95 and max.
- Network changes run under a file lock, and the shared NAT rule is removed only when no VM is registered
  (checked inside the lock). `iptables` runs with `-w`.
- `list` shows the pool and state of each VM. A 0.2.x state database is upgraded automatically.
- 49 unit tests.

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
