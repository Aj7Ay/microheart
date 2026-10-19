# Root file system for a Firecracker microVM.
# Base: Alpine Linux. Init system: OpenRC.
# This follows the recipe in docs/rootfs-and-kernel-setup.md (official Firecracker docs).
# Status: alpha, not yet tested on a real host.

FROM alpine:3.20

# Packages:
#   openrc          the init system (starts services at boot)
#   util-linux      gives the agetty program (serial console login)
#   openssh         the SSH server
#   iproute2        the "ip" command
#   curl, ca-certificates   test tools for the network
RUN apk add --no-cache openrc util-linux openssh iproute2 curl ca-certificates

# Serial console login on ttyS0 (from the official doc).
RUN ln -s agetty /etc/init.d/agetty.ttyS0 \
 && echo ttyS0 > /etc/securetty

# Config files: network, DNS at boot, console options.
COPY files/ /
RUN chmod 755 /etc/local.d/*.start

# SSH: allow root login with a key only. No passwords.
RUN echo "PermitRootLogin prohibit-password" >> /etc/ssh/sshd_config \
 && echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

# Services.
# boot level: special file systems, host name, root file system, network.
# default level: console login, SSH, local scripts (DNS).
RUN rc-update add devfs boot \
 && rc-update add procfs boot \
 && rc-update add sysfs boot \
 && rc-update add hostname boot \
 && rc-update add bootmisc boot \
 && rc-update add root boot \
 && rc-update add networking boot \
 && rc-update add agetty.ttyS0 default \
 && rc-update add sshd default \
 && rc-update add local default

# No SSH key and no password go into this image.
# The build script adds the public key to the disk file after the build.
