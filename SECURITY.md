# Security policy

microheart is alpha software. It runs as root, changes host networking (TAP device, `iptables` NAT)
and starts virtual machines. Read the code before you use it on a machine that matters.

## Report a problem

Do **not** open a public issue for a security bug. Use GitHub's private report:
**Security tab > Report a vulnerability** on https://github.com/Aj7Ay/microheart

Give the version, your steps, and what you expected. Expect a first reply within 7 days.

## Known limits (not bugs)

- The guest accepts SSH with one key only. The console has no working login (root has no password).
- The guest has NAT access to the host network and the internet.
- Firecracker's `jailer` is not used yet. Do not run untrusted code with this tool alone.
