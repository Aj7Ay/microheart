<p align="center">
  <img src="https://raw.githubusercontent.com/Aj7Ay/microheart/main/microheart.png" alt="microheart: run Firecracker microVMs with one command" width="100%">
</p>

# microheart

**Boot a [Firecracker](https://firecracker-microvm.github.io/) microVM with one command or three lines of Python.**
No Python dependencies. Linux with KVM only.

> **Unofficial. Not affiliated with or endorsed by Amazon Web Services.** "Firecracker" is an AWS project and name.
>
> **Status: alpha.** The code has not been tested on a real host yet. Test it before you rely on it.
> See [SECURITY.md](SECURITY.md) for the known limits.

## What it does

Firecracker is a very small virtual machine monitor (3.6 MB). It starts a Linux guest in about a second,
but you must do many manual steps first: get the binary, get a kernel, build a disk, make a network
device, set NAT, write the API calls. microheart does these steps for you.

| Step | By hand | With microheart |
|---|---|---|
| Firecracker binary | download, unpack | `fetch` (or bundled in the wheel) |
| Guest kernel | find on S3, download | `fetch` (or bundled in the wheel) |
| Root disk | Docker image, export, `mkfs.ext4` | `build-rootfs` |
| Network | `ip tuntap`, `iptables`, forwarding | `up` |
| Boot | 5 curl calls to the API socket | `up` (one `--config-file`) |
| Login | key, route, DNS inside the guest | key, route and DNS are in the disk |
| Clean up | remove TAP and NAT rule | `down` |

## Requirements

**To run a VM**

- Linux, `x86_64` (or `aarch64`), with `/dev/kvm` readable and writable by root
- Root access (`sudo`): TAP devices and `iptables` need it
- `ip`, `iptables`, `sysctl`, `ssh` (normally present)
- Python 3.9 or newer
- A virtualization-capable host. A cloud VM works if nested virtualization is on (tested idea: DigitalOcean droplet)

**To build the root disk (once, on any machine)**

- Docker, `mkfs.ext4`, `e2fsck`, `ssh-keygen`

Docker is **not** needed to run the VM. Build the disk once and copy the `.ext4` file.

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
    microheart down                  # stop the VM, remove tap0 and the NAT rule

Run these as root (`sudo -i` first, or put `sudo` in front). Files go to `~/.cache/microheart/` (change with `MICROHEART_HOME`). With `sudo`, `~` is root's home.

## Command reference

| Command | What it does |
|---|---|
| `microheart fetch` | Get the Firecracker binary and the newest CI kernel into the cache. |
| `microheart build-rootfs [--size 512M] [--output FILE]` | Build the ext4 disk from the bundled `Dockerfile`. Make an ed25519 key if none exists. |
| `microheart up` | Make `tap0`, set NAT, write the config file, start Firecracker, wait for SSH. |
| `microheart ssh [command...]` | SSH to the guest at `172.16.0.2` with the generated key. |
| `microheart status` | Print `running (pid N)` or `stopped`. |
| `microheart console [-n 40]` | Show the last lines of the guest console. |
| `microheart down` | Stop the VM and remove the TAP device and NAT rule. |

Global options (before the command): `--rootfs FILE`, `--key FILE`, `--vcpu N` (default 1), `--mem MIB` (default 256).

## Python API

    from microheart import MicroVM

    with MicroVM("alpine.ext4", "vm_key", vcpu=2, mem_mib=512) as vm:
        print(vm.ssh("uname -a").stdout)

| Member | Meaning |
|---|---|
| `MicroVM(rootfs, key, vcpu=1, mem_mib=256, tap="tap0", run_dir=None)` | Describe a VM. Nothing starts yet. |
| `.start(wait=60)` | Boot. Return the seconds until SSH worked. Needs root. |
| `.stop()` | Ask the guest to reboot (Firecracker then exits). Kill it after 10 s. |
| `.clean()` | `stop()` plus remove the TAP device and NAT rule. |
| `.ssh(cmd, check=True, timeout=30)` | Run a command in the guest. Return `subprocess.CompletedProcess`. |
| `.running()`, `.pid()` | State of the Firecracker process. |
| `.machine_config()` | Read `/machine-config` from the Firecracker API. |
| `.tail(n)` | Last `n` console lines. |

## How it works

1. `assets.py` finds the Firecracker binary and kernel (bundled, then cache, then download).
2. `net.py` makes `tap0` with host IP `172.16.0.1/30`, turns on IP forwarding and adds `MASQUERADE`.
3. `vm.py` writes `vm_config.json` and starts `firecracker --config-file ... --enable-pci`.
4. The guest MAC `06:00:AC:10:00:02` and the disk's `/etc/network/interfaces` give the guest `172.16.0.2/30`
   with gateway `172.16.0.1`. DNS (`8.8.8.8`) is written at boot.
5. microheart polls SSH until the guest answers.

Network layout:

    guest eth0 172.16.0.2/30 <--virtio--> host tap0 172.16.0.1/30 --NAT--> host default interface --> internet

One VM at a time for now: the IP addresses and `tap0` are fixed.

## Root disk recipe

`src/microheart/data/` holds the recipe:

- `Dockerfile`: Alpine 3.20, OpenRC, OpenSSH, iproute2, curl. SSH is key-only.
- `files/`: network config, DNS at boot, serial console options.
- `build-rootfs.sh`: Docker image to folder, add your public key, `mkfs.ext4 -d`, `e2fsck`.

Edit the recipe to add your own packages, then run `build-rootfs` again.

## Security notes

- The serial console asks for a login, and root has no password, so you cannot log in on the console.
  Use SSH (`microheart ssh`). Use `microheart console` to read boot messages.
- SSH accepts keys only. The key is made on your machine and is never part of the package.
- The guest can reach the internet through host NAT. The guest and host `FORWARD` policy is set to `ACCEPT`.
- Firecracker's `jailer` (extra isolation) is not used yet.
- microheart runs as root and changes host network settings. Read the code first.

## Limits and roadmap

- Alpha, untested on a real host.
- One VM at a time (fixed addresses).
- No snapshots, no jailer, no multi-VM networking.
- Planned: per-VM addresses, `--config-file` options, snapshots, jailer support, `aarch64` tests.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Build a wheel with the binary and kernel inside:

    python scripts/bundle.py && python -m build --wheel
    wheel tags --platform-tag manylinux_2_17_x86_64 --remove dist/*.whl

## License

MIT, see [LICENSE](LICENSE). Third-party software (Firecracker: Apache-2.0; Linux kernel: GPL-2.0) is
downloaded or bundled unchanged. See [NOTICE](NOTICE).
