#!/usr/bin/env bash
# Build an ext4 disk file from the Dockerfile in this folder.
#
# Usage:   sudo ./build-rootfs.sh <public-key-file> [size] [output-file]
# Example: sudo ./build-rootfs.sh ~/.cache/microheart/vm_key.pub 512M alpine.ext4
#
# Steps:
#   1. Docker builds the image and writes its files into a folder.
#   2. The script adds the SSH public key and the host name to the folder.
#   3. mkfs.ext4 -d copies the folder into a new ext4 file.
#   4. e2fsck checks the new file.
set -euo pipefail

PUBKEY="${1:?Give the path of a public key file (ends in .pub)}"
SIZE="${2:-512M}"
OUT="${3:-alpine.ext4}"

[ -f "$PUBKEY" ] || { echo "ERROR: $PUBKEY does not exist"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run this script as root"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Step 1: build the image and write its files to a folder"
# "docker create" + "docker export" works with the old builder and with BuildKit.
# (Ubuntu's docker.io package has no buildx, so "docker build --output" fails there.)
# The export leaves empty /etc/hostname, /etc/hosts and /etc/resolv.conf.
# Step 2 writes the first two. The guest writes resolv.conf at boot (10-dns.start).
IMAGE="microheart-rootfs:build"
docker build -t "$IMAGE" "$(dirname "$0")"
CID="$(docker create "$IMAGE")"
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/root"
docker export "$CID" | tar -x -C "$WORK/root"
# Docker adds /.dockerenv to every container. OpenRC reads it and thinks it runs in Docker,
# so it skips the hostname and networking services. Remove it. The guest is a real VM.
rm -f "$WORK/root/.dockerenv"

echo "Step 2: add the SSH public key and the host name"
install -d -m 700 "$WORK/root/root/.ssh"
install -m 600 "$PUBKEY" "$WORK/root/root/.ssh/authorized_keys"
echo "fc-alpine" > "$WORK/root/etc/hostname"
printf '127.0.0.1 localhost\n' > "$WORK/root/etc/hosts"
mkdir -p "$WORK/root"/{dev,proc,sys,run,tmp,var}

echo "Step 3: make the ext4 file ($SIZE)"
rm -f "$OUT"
truncate -s "$SIZE" "$OUT"
mkfs.ext4 -q -d "$WORK/root" -F "$OUT"

echo "Step 4: check the file system"
e2fsck -fn "$OUT" > /dev/null && echo "OK: $OUT is a valid ext4 file system"
ls -lh "$OUT"
