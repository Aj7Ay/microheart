<p align="center">
  <img src="https://raw.githubusercontent.com/Aj7Ay/microheart/main/microheart.png" alt="microheart: run Firecracker microVMs with one command" width="100%">
</p>

# microheart

**Boot a [Firecracker](https://firecracker-microvm.github.io/) microVM with one command or three lines of Python.**
No Python dependencies. Linux with KVM only.

> **Status: alpha.** Version 0.1.2 was tested end to end with one VM on a real host (see [Tested on](#tested-on)).
> The multi-VM commands, `run` (new in 0.2.0) and the warm pool (new in 0.3.0) are **not tested on a real host yet** (see [CHANGELOG.md](CHANGELOG.md)).
> See [SECURITY.md](SECURITY.md) for the known limits.

## What it does

Firecracker is a very small virtual machine monitor (3.6 MB). It boots a Linux guest in a few seconds
(we measured 3 to 4 s until SSH worked), but you must do many manual steps first: get the binary, get a kernel, build a disk, make a network
device, set NAT, write the API calls. microheart does these steps for you.

| Step | By hand | With microheart |
|---|---|---|
| Firecracker binary | download, unpack | `fetch` (or bundled in the wheel) |
| Guest kernel | find on S3, download | `fetch` (or bundled in the wheel) |
| Root disk | Docker image, export, `mkfs.ext4` | `build-rootfs` |
| Network | `ip tuntap`, `iptables`, forwarding | `up` (one TAP device and one address per VM) |
| Boot | 5 curl calls to the API socket | `up` (one `--config-file`) |
| Login | key, route, DNS inside the guest | key, route and DNS are in the disk |
| Clean up | remove TAP and NAT rule | `down` (or `run`, which cleans up for you) |

## Requirements

**To run a VM**

- Linux, `x86_64` (or `aarch64`), with `/dev/kvm` readable and writable by root
- Root access (`sudo`): TAP devices and `iptables` need it
- `ip`, `iptables`, `sysctl`, `ssh` (normally present)
- Python 3.9 or newer
- A host with KVM. A cloud VM needs **nested virtualization**. On AWS use a `c8i`, `m8i` or `r8i` instance and
  turn on *Nested virtualization* when you launch it. See [Troubleshooting](#troubleshooting).

**To build the root disk (once, on any machine)**

- Docker, `mkfs.ext4`, `e2fsck`, `ssh-keygen`

Docker is **not** needed to run the VM. Build the disk once and copy the `.ext4` file.
Buildx is not needed. `build-rootfs` also works with the `docker.io` package from Ubuntu.

## Install

The tool needs root (TAP devices, `iptables`). Install it system-wide with
[pipx](https://pipx.pypa.io/), so that `microheart` works from any folder, also with `sudo`:

    sudo apt-get install -y pipx
    sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install microheart
    microheart --version

Update later with `sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx upgrade microheart`.

You can also use `pip install microheart`, but inside a virtual environment the command is only at
`<venv>/bin/microheart` and is not on your `PATH`. Use pipx to avoid that.

## Quick start

    microheart fetch                 # Firecracker + kernel (skipped when bundled in the wheel)
    microheart build-rootfs          # build alpine.ext4 + an SSH key (needs Docker)
    microheart up                    # boot the VM and wait for SSH
    microheart ssh uname -a          # run one command, or open a shell without arguments
    microheart down                  # stop the VM, remove its TAP device and disk copy
    microheart run -- uname -a       # new in 0.2.0: boot a temporary VM, run, remove the VM

Run these as root (`sudo -i` first, or put `sudo` in front). Files go to `~/.cache/microheart/` (change with `MICROHEART_HOME`). With `sudo`, `~` is root's home.

## Command reference

| Command | What it does |
|---|---|
| `microheart fetch` | Get the Firecracker binary and the newest CI kernel into the cache. |
| `microheart build-rootfs [--size 512M] [--output FILE]` | Build the base ext4 disk from the bundled `Dockerfile`. Make an ed25519 key if none exists. |
| `microheart up [--name NAME]` | Copy the base disk, make a TAP device, boot the VM, wait for SSH. |
| `microheart list` | Show all VMs, their state and address. |
| `microheart ssh [--name NAME] [command...]` | SSH to a VM with the generated key. |
| `microheart run [--name NAME] [--timeout 60] -- command...` | Boot a temporary VM, run the command, print its output, return its exit code, remove the VM. |
| `microheart status [--name NAME]` | Show if a VM runs. |
| `microheart console [--name NAME] [-n 40]` | Show the last lines of the guest console. |
| `microheart down [--name NAME \| --all]` | Stop VMs. Remove their disk copy and TAP device. |
| `microheart run --pool POOL [--queue-timeout 30] -- command...` | Run the command in a ready VM of a warm pool, then destroy that VM. New in 0.3.0. |
| `microheart pool create NAME [--size 3] [--vcpu 1] [--mem 256]` | Create a pool and boot its VMs. |
| `microheart pool status [NAME]` | Show size, ready, booting and leased VMs. |
| `microheart pool scale NAME --size N` | Change the size. |
| `microheart pool delete NAME` | Remove the pool and all its VMs. |
| `microheart benchmark [--count 5] [--pool NAME]` | Time cold starts, and warm dispatch with `--pool`. |

`--name`, `list`, `run` and `down --all` are new in 0.2.0 and are not tested on a real host yet.
Without `--name` the VM is called `default`. Global options (before the command): `--rootfs FILE`, `--key FILE`,
`--vcpu N` (default 1), `--mem MIB` (default 256).

### Several VMs

    microheart up --name api
    microheart up --name worker
    microheart list
    microheart ssh --name api hostname
    microheart down --all

### Run one command and throw the VM away

    microheart run --timeout 30 -- python3 -c 'print(1+1)'

The arguments go to the guest as separate words, quoted. The host shell does not interpret them. The VM is removed after
success, failure, timeout, Ctrl+C and `kill`. The exit code is the command's exit code (`124` for a timeout).
The base disk has no Python. Build your own disk (edit the `Dockerfile`) for other tools.

### Warm pool (new in 0.3.0, not tested on a real host yet)

A cold `run` boots a VM for every command (3 to 4 s until SSH worked in our test). A pool boots VMs **before**
they are needed:

    microheart pool create py --size 5          # boot 5 ready VMs
    microheart run --pool py -- uname -a        # takes one, runs the command, destroys it
    microheart pool status                      # a replacement is booting in the background
    microheart benchmark --count 10 --pool py   # compare cold start and warm dispatch
    microheart pool delete py

Rules:

- **One job per VM.** After the job the VM is destroyed, never reused. The next job never sees its files, processes or
  credentials. A replacement boots in the background from the clean base disk.
- **Atomic.** Two jobs never get the same VM, and parallel refills never boot more VMs than the pool size.
- **Bounded waiting.** If no VM is ready, the job waits up to `--queue-timeout` seconds, then fails with a clear error.
- **No daemon.** `run --pool` starts a detached `microheart pool refill`. Its log is `~/.cache/microheart/pool-refill.log`.
- A pool VM whose process died is removed and replaced on the next refill.
- The pool uses SSH to run commands. We have **no measured numbers** for warm dispatch yet. Run `benchmark` on your host.
- Idle pool VMs have the same network access as any VM (NAT to the internet). A per-VM firewall is not built yet.

## Python API

    from microheart import MicroVM

    with MicroVM("job1", "alpine.ext4", "vm_key", vcpu=2, mem_mib=512) as vm:
        r = vm.run(["uname", "-a"], timeout=10)
        print(r.stdout, r.returncode)

| Member | Meaning |
|---|---|
| `MicroVM(name="default", rootfs, key, vcpu=1, mem_mib=256)` | Describe a VM. Nothing starts yet. `rootfs` is the base disk. |
| `.start(wait=60)` | Copy the disk, boot, wait for SSH. Return the seconds, or `None` if it already runs. Needs root. |
| `.run(argv, timeout=60)` | Run a command in the guest. Return `subprocess.CompletedProcess`. |
| `.ssh(cmd, check=True, timeout=30)` | Run a shell command string in the guest. |
| `.stop()` | Ask the guest to reboot (Firecracker then exits). Kill it after 10 s. |
| `.clean()` | `stop()` plus remove the TAP device, disk copy and record. |
| `.running()`, `.pid()` | State of the Firecracker process. |
| `.tail(n)` | Last `n` console lines. |

## How it works

1. `assets.py` finds the Firecracker binary and kernel (bundled, then cache, then download).
2. `state.py` keeps a small SQLite registry. Each VM gets a unique index. The index decides its `/30` network
   (`172.16.x.y`), its TAP device (`mh<index>`) and its MAC address. Index 0 is `172.16.0.1` (host) and `172.16.0.2` (guest).
3. `vm.py` copies the base disk for the VM, calls `net.py` (TAP device, forwarding, one shared `MASQUERADE` rule),
   writes `vm_config.json` and starts `firecracker --config-file ... --enable-pci`.
4. The VM's address goes to the guest on the kernel command line (`microheart.ip=`, `microheart.gw=`, `microheart.name=`).
   A boot script in the disk (`/etc/local.d/05-net.start`) sets the address, the route and the host name.
   So one disk works for every VM. DNS (`8.8.8.8`) is written at boot.
5. microheart polls SSH until the guest answers.
6. A pool (`pool.py`) is a name, a size and a VM profile in the registry. `refill` reserves the missing VMs in one
   transaction and boots them in parallel. `lease` marks the oldest ready VM as leased in one transaction.
   A VM goes `booting` > `ready` > `leased` > destroyed.

Network layout, for each VM:

    guest eth0 172.16.x.2/30 <--virtio--> host mh<N> 172.16.x.1/30 --NAT--> host default interface --> internet

The shared NAT rule is removed when the last VM goes down.

## Root disk recipe

`src/microheart/data/` holds the recipe:

- `Dockerfile`: Alpine 3.20, OpenRC, OpenSSH, iproute2, curl. SSH is key-only.
- `files/`: boot scripts: the address from the kernel command line (`05-net.start`) and DNS (`10-dns.start`).
- `build-rootfs.sh`: Docker image to folder, add your public key, `mkfs.ext4 -d`, `e2fsck`.

Edit the recipe to add your own packages, then run `build-rootfs` again.

## Security notes

- The serial console asks for a login, and root has no password, so you cannot log in on the console.
  Use SSH (`microheart ssh`). Use `microheart console` to read boot messages.
- SSH accepts keys only. The key is made on your machine and is never part of the package.
- The guest can reach the internet through host NAT. microheart sets `iptables -P FORWARD ACCEPT` for the whole host.
- `run` passes the command to the guest as separate quoted words. The host shell never interprets them.
- Firecracker's `jailer` (extra isolation) is not used yet.
- microheart runs as root and changes host network settings. Read the code first.

## Limits and roadmap

- Alpha. Single VM tested on a real host (0.1.2). Multi-VM, `run` (0.2.0) and the warm pool (0.3.0) are not.
- The pool has no background service: replacements start when a job finishes. If nobody runs jobs, a crashed pool VM stays
  until the next `run --pool` or `pool refill`.
- VMs reach each other and the host through the TAP network (no per-VM firewall yet).
- No snapshots, no jailer.
- Planned: a vsock guest agent (no SSH), per-VM firewall, jailer support, snapshots, a host API.

## Tested on

| Item | Value |
|---|---|
| Version | 0.1.2, one VM: install, `fetch`, `build-rootfs`, `up`, `ssh`, internet from the guest, `down` |
| Host | AWS `c8i.large`, nested virtualization on, Ubuntu 24.04, Docker CE |
| Firecracker | v1.17.0 |
| Guest kernel | 6.18.54 (Firecracker CI build) |
| Time to SSH | 3.2 to 4.2 s |

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `/dev/kvm` does not exist | The host does not give KVM to the guest. Check `grep -c -E 'vmx\|svm' /proc/cpuinfo`. If it prints `0`, turn on nested virtualization. On AWS this is a launch option, so you must set it when you create the instance. |
| `kvm_intel: VMX not supported` | Same cause. The instance type or setting does not allow nested virtualization. |
| `unknown flag: --output` in `build-rootfs` | Old version (0.1.0) with a Docker that has no buildx. Upgrade to 0.1.1 or newer. |
| `no SSH after 60 s` | microheart prints the last console lines and removes the VM. Run `microheart console` for more. In 0.1.0, a disk made by `docker export` kept `/.dockerenv`, so OpenRC skipped the network. Rebuild the disk with 0.1.1 or newer. |
| `(none) login:` on the console, no SSH | The same `/.dockerenv` problem. Rebuild the disk. |
| A VM stays after a crash | `microheart down --all` (0.2.0 and newer). It also removes stale records. |
| `no ready VM in pool` | All pool VMs are busy or still booting. Wait, raise `--queue-timeout`, or make the pool bigger (`pool scale`). Check `pool status` and `~/.cache/microheart/pool-refill.log`. |
| `microheart: command not found` | The venv is not on your `PATH`. Install with pipx, or run `source <venv>/bin/activate`. |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Build a wheel with the binary and kernel inside:

    python scripts/bundle.py && python -m build --wheel
    wheel tags --platform-tag manylinux_2_17_x86_64 --remove dist/*.whl

## License

MIT, see [LICENSE](LICENSE). Third-party software (Firecracker: Apache-2.0; Linux kernel: GPL-2.0) is
downloaded or bundled unchanged. See [NOTICE](NOTICE).
