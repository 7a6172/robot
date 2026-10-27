# Stable target identity across address changes — measured facts and design

Status: **design + measurement only. Not implemented.** The integration work
(scan → localization, TF ownership) took priority; this records what was verified about the
real hardware so the implementation does not start from assumptions.

## What is actually available on swjtumover05

Measured read-only, as the unprivileged `swjtumover` user:

| identifier | available | usable as a distinguishing identity? |
| --- | --- | --- |
| `/sys/class/dmi/id/sys_vendor` | `Default string` | no — generic mini-PC SMBIOS |
| `/sys/class/dmi/id/product_name` | `Default string` | no |
| `/sys/class/dmi/id/board_name` | `Default string` | no |
| `product_serial`, `product_uuid`, `board_serial` | present but **unreadable** | not without root |
| `/etc/machine-id` | `2c7c442a1da8…` | yes — changes only on OS reinstall |
| MAC `wlp2s0` | `bc:fd:0c:c2:56:81` | yes — the management interface |
| MAC `enp1s0` | `68:1d:ef:5a:d1:93` | yes, but this is the **LiDAR** network |
| MAC `enp3s0` | `68:1d:ef:5a:d1:94` | yes, but this is the **motor/IO** network |
| SSH host keys | ECDSA / ED25519 `SHA256:+6Q4z…` / RSA | yes — the cryptographic identity |
| CPU model | Intel N150 | classification only; identical across the fleet |

Consequences for the design:

* DMI cannot carry identity on this hardware class. It must be collected best-effort and
  recorded with low confidence, never required.
* Serial numbers need root. Not available, so not a dependency.
* The three interfaces have distinct roles and must be classified, or the LiDAR/motor
  addresses would be mistaken for management endpoints. Management = interface carrying the
  default route or a wireless interface; internal = other interfaces with an address.

## Proposed model

Separate the five things that are currently conflated in `Target`:

1. **Logical identity** — `Target.name`, already stable and already the CLI handle. Unchanged.
2. **Endpoints** — a list of observations `{address, interface, role, last_seen, verified}`,
   management and internal, instead of one `host`. `host` stays as the active endpoint so
   existing behaviour and configs keep working.
3. **Hardware observations** — `{field, value, source, confidence}` rather than one hash, so a
   changed field degrades confidence instead of invalidating the whole record.
4. **SSH host-key fingerprints** per algorithm — the only field that may *prove* identity.
5. **Capabilities** — already separate (`TargetEnvironment`, discovered capabilities).

## Verification rule

A candidate endpoint is only *proposed* by discovery. It is accepted after its SSH host key
matches the enrolled fingerprint, checked with `StrictHostKeyChecking=yes` against a caasi-
managed known_hosts file for that target — never `accept-new` on refresh, and never disabled.
A differing key is reported as a conflict, distinguishing (a) same `machine-id`, same MACs →
key rotation, (b) different `machine-id`, same MACs → OS reinstall, (c) different MACs → a
different machine. Replacing trusted identity requires an explicit re-enrolment command.

## Discovery

Bounded scan of explicitly configured management subnets only (`discovery.subnets` in the
target config), capped in size, TCP-22 probe then `ssh-keyscan` compared against enrolled
fingerprints. No daemon, no unbounded scanning, and no trust in the address itself. mDNS /
DNS-SD and DHCP reservations are extension points, not implemented.

## Open questions for implementation

* Where recorded identity lives (`~/.caasi/identity/<target>.json`) and how it migrates.
* Whether `caasi target refresh` should update the config file in place or only report.
* Rate/duplicate handling when two candidates present the same key (cloned image).
