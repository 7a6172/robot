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

---

# Implemented behaviour

`src/caasi/core/identity.py`, `caasi target enroll|identity|discover|refresh|reenroll`.

## Trust boundary

| operation | may it learn a host key? | may it replace a trusted key? | may it change config? |
| --- | --- | --- | --- |
| `enroll` | yes (explicit user action) | only with `--accept-identity-change` | no |
| `identity` | no | no | no |
| `discover` | no — candidates are compared, never adopted | no | no |
| `refresh` | no | no | only with `--apply`, and only `host`/`port` |
| `reenroll` | yes | yes, requires the flag | no |

An address is only ever a *candidate*. It becomes usable when its host key matches the
enrolled record. Hardware observations (machine-id, MACs) are recorded for diagnosis and
never participate in the accept/reject decision.

## Where verification happens

`targets.target_ssh_prefix()` is the single SSH choke point for exec, build, deploy,
artifacts, lifecycle, ROS and the target probe. If the target has an identity record it now
emits:

```
-o StrictHostKeyChecking=yes
-o UserKnownHostsFile=~/.caasi/identity/<name>.known_hosts
-o GlobalKnownHostsFile=/dev/null
```

The managed file is written from the *enrolled* keys for the current address, which is what
makes a DHCP change survivable: a new address presenting a different key fails closed instead
of being accepted. Targets without a record keep `accept-new` against the user's
`known_hosts`, so existing configurations behave exactly as before. `StrictHostKeyChecking=no`
is never emitted anywhere.

Verified on the real link: with a deliberately wrong key in the managed file,
`ssh` reports `Host key verification failed`; with the real record,
`caasi target check` and `caasi target exec` continue to work.

## Configuration

```yaml
targets:
  swjtumover05:
    host: 10.212.19.94          # current endpoint; NOT identity
    user: swjtumover
    ssh_timeout: 30.0
    tags: [robot, swjtumover, wifi, jazzy]

discovery:                      # required for discovery; explicit and bounded
  subnets: [10.212.19.0/24]     # only these are ever scanned
  timeout: 0.3                  # per-address TCP probe
  max_hosts: 254                # a subnet with more usable addresses is refused
  concurrency: 64
```

Trust records live in `~/.caasi/identity/<name>.json` (mode 0600) with
`<name>.known_hosts` beside them — separate from the config file, because they are recorded
facts rather than user settings.

## Outcomes and exit codes

| `discover` status | meaning | exit |
| --- | --- | --- |
| `verified` | exactly one address presents the enrolled key | 0 |
| `no-candidates` | the subnet was scanned, nothing answered on 22 | 1 |
| `no-match` | hosts answered, none presented the enrolled key | 1 |
| `ambiguous` | two or more addresses present the enrolled key (cloned image) | 2 |
| `conflict` | the address in use presents different keys | 2 |
| `not-configured` | no `discovery.subnets` and no `--subnet` | 3 |
| `scan-failed` | invalid subnet, or larger than the cap | 4 |

`not-configured` and `scan-failed` are separate from "nothing found" on purpose: an
unavailable discovery mechanism must never be reported as an offline robot.

## What the robot actually reported

Enrolled from `swjtumover05`: three SSH host keys (ECDSA, ED25519, RSA), `machine_id`,
`hostname`, `cpu_model`, `arch`, and interfaces classified as
`mac.management` = `bc:fd:0c:c2:56:81` (`wlp2s0`),
`mac.internal.enp1s0` / `mac.internal.enp3s0` (the LiDAR and motor/IO links). DMI values
(`Default string`) and the unreadable serials are dropped rather than stored.

Bounded discovery over the configured `/24` scanned 254 addresses in 2.2 s: the robot
verified at `10.212.19.94`, and the workstation at `10.212.19.98` was correctly *not*
accepted. Refreshing against the workstation was refused with an explicit "does not match the
enrolled identity" message rather than being used.

## Remaining environmental requirements

Not implemented, and each needs authorization because it changes network or system state:

* **DHCP reservation or manageed DNS** would make discovery unnecessary. Recommended for a
  fleet: reserve one address per robot by MAC (`mac.management` is recorded for exactly this)
  and point caasi at a stable name. Both were out of scope here.
* **mDNS/DNS-SD** is a candidate extension point (`avahi` on the robot), not implemented — it
  would need a robot-side service, i.e. an installation decision.
* **Subnet scanning does not scale to a flat /16**: the cap refuses such a subnet by design.
  A fleet needs either reservations, DNS, or a narrow configured subnet.
* **Key rotation without re-enrolment**: deliberate by design. A reinstalled robot requires
  `caasi target reenroll <name> --accept-identity-change`, which prints the enrolled and
  observed fingerprints first.
* Cloned images (identical `machine-id` *and* identical host keys) are reported as
  `ambiguous` and never auto-resolved; distinguishing them needs per-unit provisioning.
