"""Stable target identity: enrolled trust records, verification and bounded discovery.

A target's *name* is its identity. Its address is only a current endpoint, and an address by
itself proves nothing: any machine can answer on a reused DHCP lease. This module records
what a target was enrolled as — its SSH host keys and best-effort hardware observations —
and verifies candidate endpoints against that record before they are used or persisted.

Design rules, all enforced here rather than by convention:

* discovery may only *propose* an endpoint; acceptance requires a matching enrolled host key
* host keys are verified strictly (``StrictHostKeyChecking=yes`` against a caasi-managed
  known_hosts file). ``accept-new`` is used only while enrolling, and ``no`` never
  (``plan/phases/phase-08/target-identity-design.md``)
* hardware observations (machine-id, MACs) diagnose *why* two records differ; they never
  override or weaken key verification
* replacing trusted fingerprints requires an explicit re-enrolment
* discovery is bounded: explicitly configured management subnets, a host cap, a concurrency
  cap and a per-candidate timeout
* resolving an endpoint and persisting it are separate steps

Nothing here runs a daemon or scans anything that was not configured.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import Config

#: Hardware observations this module understands, with the confidence each deserves on the
#: hardware class caasi actually manages. Generic mini-PC SMBIOS reports "Default string"
#: and hides serials behind root (measured on swjtumover05), so DMI ranks lowest.
FIELD_CONFIDENCE = {
    "machine_id": "strong",     # stable per OS install; changes on reinstall
    "mac.management": "strong",
    "mac.internal": "strong",
    "ssh.host_keys": "authoritative",
    "dmi.product_name": "weak",
    "dmi.sys_vendor": "weak",
    "dmi.product_serial": "weak",
    "cpu_model": "classification",  # identical across a fleet of the same model
    "hostname": "weak",             # operator-chosen, not identity
}

#: Values that carry no distinguishing information and must not be stored as identity.
UNUSABLE_VALUES = {"", "default string", "to be filled by o.e.m.", "system serial number",
                   "none", "unknown", "not specified", "0"}

DEFAULT_SCAN_TIMEOUT = 0.3
DEFAULT_MAX_HOSTS = 256
DEFAULT_CONCURRENCY = 32
DEFAULT_KEYSCAN_TIMEOUT = 2.0

# Discovery outcomes. Distinct on purpose: "discovery is not configured" must never be
# reported as "your robot is offline".
VERIFIED = "verified"
NO_MATCH = "no-match"
NO_CANDIDATES = "no-candidates"
AMBIGUOUS = "ambiguous"
CONFLICT = "conflict"
NOT_CONFIGURED = "not-configured"
SCAN_FAILED = "scan-failed"


# --------------------------------------------------------------------------- storage

def identity_root(config: Config | None = None) -> Path:
    """Where trust records live. Kept out of the config file: they are not user settings."""
    if config is not None:
        configured = config.get("identity.root")
        if configured:
            return Path(str(configured)).expanduser()
    return Path.home() / ".caasi" / "identity"


def record_path(name: str, config: Config | None = None) -> Path:
    return identity_root(config) / f"{name}.json"


@dataclass
class Observation:
    """One hardware observation, with where it came from and how much it is worth."""

    field: str
    value: str
    source: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Endpoint:
    """An address this target has been seen at. Not an identity."""

    address: str
    port: int = 22
    role: str = "management"  # management | internal
    interface: str | None = None
    verified: bool = False
    first_seen: float = 0.0
    last_seen: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IdentityRecord:
    name: str
    enrolled_at: float = 0.0
    updated_at: float = 0.0
    #: key algorithm -> {"public": base64 key material, "fingerprint": "SHA256:..."}
    ssh_keys: dict[str, dict[str, str]] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    notes: str = ""

    # -- helpers -------------------------------------------------------
    def fingerprints(self) -> dict[str, str]:
        return {algo: data.get("fingerprint", "") for algo, data in self.ssh_keys.items()}

    def fingerprint_set(self) -> set[str]:
        return {fp for fp in self.fingerprints().values() if fp}

    def observation_map(self) -> dict[str, str]:
        return {o.field: o.value for o in self.observations}

    def management_endpoints(self) -> list[Endpoint]:
        return [e for e in self.endpoints if e.role == "management"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enrolled_at": self.enrolled_at,
            "updated_at": self.updated_at,
            "ssh_keys": self.ssh_keys,
            "observations": [o.to_dict() for o in self.observations],
            "endpoints": [e.to_dict() for e in self.endpoints],
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "IdentityRecord":
        return IdentityRecord(
            name=str(data.get("name", "")),
            enrolled_at=float(data.get("enrolled_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            ssh_keys={str(k): dict(v) for k, v in (data.get("ssh_keys") or {}).items()},
            observations=[Observation(**o) for o in (data.get("observations") or [])],
            endpoints=[Endpoint(**e) for e in (data.get("endpoints") or [])],
            notes=str(data.get("notes") or ""),
        )


def load_record(name: str, config: Config | None = None) -> IdentityRecord | None:
    path = record_path(name, config)
    try:
        return IdentityRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_record(record: IdentityRecord, config: Config | None = None) -> Path:
    path = record_path(record.name, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    record.updated_at = record.updated_at or time.time()
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=False), encoding="utf-8")
    try:
        path.chmod(0o600)  # a trust record is not world-readable
    except OSError:
        pass
    return path


# --------------------------------------------------------------- strict verification

def managed_known_hosts(record: IdentityRecord, config: Config | None = None) -> Path:
    """The known_hosts file caasi verifies this target against.

    Written from the *enrolled* keys for whatever address is current, which is what makes a
    DHCP change survivable without ever trusting an unverified key: a new address presenting
    a different key fails verification instead of being accepted.
    """
    return identity_root(config) / f"{record.name}.known_hosts"


def write_managed_known_hosts(record: IdentityRecord, config: Config | None = None) -> Path:
    path = managed_known_hosts(record, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    addresses = [e for e in record.endpoints if e.role == "management"] or record.endpoints
    for endpoint in addresses:
        host = endpoint.address if endpoint.port == 22 else f"[{endpoint.address}]:{endpoint.port}"
        for algo, data in sorted(record.ssh_keys.items()):
            public = data.get("public", "").strip()
            if public:
                lines.append(f"{host} {algo} {public}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


# ------------------------------------------------------------------------ key scanning

def _ssh_keyscan(
    address: str,
    port: int = 22,
    timeout: float = DEFAULT_KEYSCAN_TIMEOUT,
) -> dict[str, dict[str, str]]:
    """Read a host's public keys. Returns ``{algo: {public, fingerprint}}``.

    This is the only place a key is learned rather than verified, and it is only used for
    candidates and for enrolment. Nothing here authenticates anything yet.
    """
    try:
        proc = subprocess.run(
            ["ssh-keyscan", "-T", str(int(max(1, timeout))), "-p", str(port), address],
            capture_output=True,
            text=True,
            timeout=max(2.0, timeout + 2.0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    keys: dict[str, dict[str, str]] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        algo, public = parts[1], parts[2]
        keys[algo] = {"public": public, "fingerprint": _fingerprint(algo, public)}
    return keys


def _fingerprint(algo: str, public: str) -> str:
    """SHA256 fingerprint of a base64 public key, as ssh-keygen prints it."""
    import base64
    import hashlib

    try:
        blob = base64.b64decode(public)
    except Exception:
        return ""
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


def compare_keys(
    enrolled: dict[str, dict[str, str]],
    observed: dict[str, dict[str, str]],
) -> str:
    """How an observed key set relates to the enrolled one.

    ``match``      — every algorithm the target enrolled is still presented
    ``rotated``    — same algorithms, different material (key regeneration or reinstall)
    ``partial``    — some enrolled algorithms match, others are missing or differ
    ``mismatch``   — nothing enrolled is presented: a different machine, or a rebuilt one
    """
    enrolled_algos = {a for a, d in enrolled.items() if d.get("public")}
    if not enrolled_algos or not observed:
        return "mismatch"
    matching = [a for a in enrolled_algos if a in observed
                and observed[a].get("public") == enrolled[a].get("public")]
    if len(matching) == len(enrolled_algos):
        return "match"
    if matching:
        return "partial"
    if enrolled_algos & set(observed):
        return "rotated"
    return "mismatch"


# ----------------------------------------------------------------- hardware fingerprint

def _classify_interface(name: str, has_default_route: bool) -> str:
    """Management or internal.

    A robot's LiDAR and motor-controller links are Ethernet interfaces with addresses but no
    default route. Treating those as management endpoints would offer the wrong address for
    the wrong network -- the exact mistake this classification exists to prevent.
    """
    wireless = name.startswith(("wl", "wlan"))
    if has_default_route or wireless:
        return "management"
    return "internal"


REMOTE_IDENTITY_SCRIPT = r"""
import json, os, platform

def read(path):
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except Exception:
        return ''

def default_route_iface():
    try:
        with open('/proc/net/route', 'r') as f:
            next(f)
            for line in f:
                parts = line.split()
                if len(parts) > 2 and parts[1] == '00000000':
                    return parts[0]
    except Exception:
        pass
    return ''

def interfaces():
    out = []
    default_iface = default_route_iface()
    try:
        names = [n for n in os.listdir('/sys/class/net') if n != 'lo']
    except Exception:
        names = []
    for name in sorted(names):
        base = '/sys/class/net/' + name
        mac = read(base + '/address')
        if not mac or mac == '00:00:00:00:00:00':
            continue
        # IPv4 addresses, if any (read-only, no interface change).
        addrs = []
        try:
            import socket
            import struct
            import fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            packed = struct.pack('256s', name[:15].encode())
            res = fcntl.ioctl(s.fileno(), 0x8915, packed)
            addrs.append(socket.inet_ntoa(res[20:24]))
            s.close()
        except Exception:
            pass
        out.append({
            'name': name,
            'mac': mac,
            'addresses': addrs,
            'default_route': name == default_iface,
        })
    return out

out = {
    'machine_id': read('/etc/machine-id') or read('/var/lib/dbus/machine-id'),
    'hostname': platform.node(),
    'cpu_model': '',
    'arch': platform.machine(),
    'dmi': {
        'sys_vendor': read('/sys/class/dmi/id/sys_vendor'),
        'product_name': read('/sys/class/dmi/id/product_name'),
        'product_serial': read('/sys/class/dmi/id/product_serial'),
        'product_uuid': read('/sys/class/dmi/id/product_uuid'),
    },
    'interfaces': interfaces(),
}
try:
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'model name' in line:
                out['cpu_model'] = line.split(':', 1)[1].strip()
                break
except Exception:
    pass
print(json.dumps(out))
"""


def _probe_hardware(target: Any) -> dict[str, Any]:
    """Read-only hardware observations over SSH. Reuses the one ssh path caasi has."""
    from . import execution, targets as targets_core

    result = execution.run_on_target(
        target,
        execution.ExecRequest(
            argv=["python3", "-c", REMOTE_IDENTITY_SCRIPT.strip()],
            timeout=max(10.0, float(getattr(target, "ssh_timeout", 3.0))),
        ),
    )
    if not result.ok:
        return {}
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


def build_observations(raw: dict[str, Any], config: Config | None = None) -> list[Observation]:
    """Turn a probe result into stored observations, dropping values that identify nothing."""
    observations: list[Observation] = []

    def add(field_name: str, value: str, source: str) -> None:
        text = str(value or "").strip()
        if text.lower() in UNUSABLE_VALUES:
            return
        # Per-interface fields are qualified (``mac.internal.enp1s0``), so resolve the
        # confidence of their family rather than falling back to "weak".
        confidence = FIELD_CONFIDENCE.get(field_name)
        if confidence is None:
            family = ".".join(field_name.split(".")[:2])
            confidence = FIELD_CONFIDENCE.get(family, "weak")
        observations.append(Observation(field_name, text, source, confidence))

    add("machine_id", raw.get("machine_id", ""), "probe:/etc/machine-id")
    add("hostname", raw.get("hostname", ""), "probe:platform.node")
    add("cpu_model", raw.get("cpu_model", ""), "probe:/proc/cpuinfo")
    add("arch", raw.get("arch", ""), "probe:platform.machine")
    dmi = raw.get("dmi") or {}
    for key in ("sys_vendor", "product_name", "product_serial", "product_uuid"):
        add(f"dmi.{key}", dmi.get(key, ""), f"probe:/sys/class/dmi/id/{key}")

    for iface in raw.get("interfaces") or []:
        mac = str(iface.get("mac", "")).strip()
        if not mac or mac.lower() in UNUSABLE_VALUES:
            continue
        name = str(iface.get("name", "")).strip()
        role = _classify_interface(name, bool(iface.get("default_route")))
        # The management NIC identifies the endpoint. Internal NICs prove it is the same
        # chassis but are qualified by interface, because a robot has several and a single
        # ``mac.internal`` field would silently keep only the last one.
        suffix = "" if role == "management" else (f".{name}" if name else "")
        add(f"mac.{role}{suffix}", mac, f"probe:/sys/class/net/{name}/address")
        for address in iface.get("addresses") or []:
            add(f"address.{role}{suffix}", address, f"probe:ioctl:{name}")
    return observations


def management_addresses(raw: dict[str, Any]) -> list[str]:
    """IPv4 addresses on interfaces classified as management."""
    found: list[str] = []
    for iface in raw.get("interfaces") or []:
        role = _classify_interface(str(iface.get("name", "")), bool(iface.get("default_route")))
        if role != "management":
            continue
        found.extend(str(a) for a in (iface.get("addresses") or []))
    return found


# ------------------------------------------------------------------------ verification

def verify_address(
    record: IdentityRecord,
    address: str,
    port: int = 22,
    timeout: float = DEFAULT_KEYSCAN_TIMEOUT,
) -> tuple[str, dict[str, dict[str, str]]]:
    """Check one candidate address against the enrolled keys.

    Returns ``(relation, observed_keys)`` where relation is what :func:`compare_keys`
    reported, or ``"unreachable"`` when the host answers nothing.
    """
    observed = _ssh_keyscan(address, port, timeout)
    if not observed:
        return "unreachable", {}
    return compare_keys(record.ssh_keys, observed), observed


# ---------------------------------------------------------------------- enumeration

@dataclass
class Candidate:
    address: str
    relation: str  # match | rotated | partial | mismatch
    observed: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "relation": self.relation,
            "observed_fingerprints": {a: d.get("fingerprint", "")
                                      for a, d in self.observed.items()},
        }


@dataclass
class DiscoveryResult:
    status: str
    candidates: list[Candidate] = field(default_factory=list)
    scanned: int = 0
    live: int = 0
    duration_s: float = 0.0
    subnets: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def verified(self) -> list[Candidate]:
        return [c for c in self.candidates if c.relation == "match"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidates": [c.to_dict() for c in self.candidates],
            "scanned": self.scanned,
            "live": self.live,
            "duration_s": round(self.duration_s, 3),
            "subnets": self.subnets,
            "error": self.error,
        }


def resolve_subnets(config: Config | None, override: Iterable[str] | None = None) -> list[str]:
    """The subnets discovery is allowed to touch. Empty means discovery is not configured."""
    raw: list[str] = []
    if override:
        raw = [str(s) for s in override]
    elif config is not None:
        configured = config.get("discovery.subnets")
        if isinstance(configured, str):
            raw = [configured]
        elif isinstance(configured, (list, tuple)):
            raw = [str(s) for s in configured]
    return raw


def _usable_host_count(network: ipaddress._BaseNetwork) -> int:
    """Addresses that would actually be probed (a /24 has 254, not 256)."""
    if network.version == 4 and network.prefixlen <= 30:
        return max(0, network.num_addresses - 2)
    return network.num_addresses


def _expand(subnets: list[str], max_hosts: int) -> tuple[list[str], str]:
    """Enumerate bounded address space. Returns (addresses, error)."""
    addresses: list[str] = []
    for subnet in subnets:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError as err:
            return [], f"invalid subnet {subnet!r}: {err}"
        # Scanning only part of a configured subnet would produce a misleading "no
        # candidates", so a subnet larger than the whole cap is refused rather than
        # truncated. Several smaller subnets are accumulated up to the cap instead.
        usable = _usable_host_count(network)
        if usable > max_hosts:
            return addresses, (
                f"subnet {subnet} has {usable} usable addresses; the cap is "
                f"{max_hosts}. Narrow the subnet or raise discovery.max_hosts."
            )
        hosts = network.hosts() if network.num_addresses > 2 else network
        for host in hosts:
            if len(addresses) >= max_hosts:
                break
            addresses.append(str(host))
        if len(addresses) >= max_hosts:
            break
    return addresses, ""


def discover(
    record: IdentityRecord,
    config: Config | None = None,
    *,
    subnets: Iterable[str] | None = None,
    port: int = 22,
    timeout: float = DEFAULT_SCAN_TIMEOUT,
    max_hosts: int | None = None,
    concurrency: int | None = None,
    keyscan_timeout: float = DEFAULT_KEYSCAN_TIMEOUT,
    connect: Callable[[str, int, float], tuple[bool, float | None]] | None = None,
    current: str | None = None,
) -> DiscoveryResult:
    """Find the enrolled target on explicitly configured management subnets only.

    Candidates are verified against the enrolled host keys; an address that answers is not a
    match. Two or more addresses presenting the enrolled key means a cloned image, which is
    reported as ambiguous rather than resolved by picking one.
    """
    from . import targets as targets_core

    start = time.perf_counter()
    chosen = resolve_subnets(config, subnets)
    if not chosen:
        return DiscoveryResult(
            status=NOT_CONFIGURED, duration_s=time.perf_counter() - start,
            error=("discovery is not configured: set discovery.subnets in the config or pass "
                   "--subnet. This is not an offline target."),
        )

    if max_hosts is None:
        max_hosts = int((config.get("discovery.max_hosts") if config else None)
                        or DEFAULT_MAX_HOSTS)
    if concurrency is None:
        concurrency = int((config.get("discovery.concurrency") if config else None)
                          or DEFAULT_CONCURRENCY)
    if timeout is None:
        timeout = DEFAULT_SCAN_TIMEOUT

    addresses, error = _expand(chosen, max_hosts)
    if error:
        return DiscoveryResult(status=SCAN_FAILED, subnets=chosen, error=error,
                               duration_s=time.perf_counter() - start)

    probe = connect or targets_core.check_socket_reachable
    live: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        results = pool.map(lambda a: (a, probe(a, port, timeout)[0]), addresses)
        for address, reachable in results:
            if reachable:
                live.append(address)

    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        relations = pool.map(
            lambda a: (a,) + verify_address(record, a, port, keyscan_timeout), live)
        for address, relation, observed in relations:
            if relation == "unreachable":
                continue
            candidates.append(Candidate(address, relation, observed))

    matches = [c for c in candidates if c.relation == "match"]
    if len(matches) == 1:
        status = VERIFIED
    elif len(matches) > 1:
        status = AMBIGUOUS
    elif current and any(c.address == current and c.relation in ("rotated", "partial")
                         for c in candidates):
        # A conflict is about *our* target: the address it was using now presents different
        # keys. A stranger elsewhere on the subnet is simply not the robot.
        status = CONFLICT
    elif candidates:
        status = NO_MATCH
    else:
        status = NO_CANDIDATES

    return DiscoveryResult(
        status=status,
        candidates=candidates,
        scanned=len(addresses),
        live=len(live),
        duration_s=time.perf_counter() - start,
        subnets=chosen,
    )


# ------------------------------------------------------------------------- enrolment

@dataclass
class EnrollResult:
    ok: bool
    record: IdentityRecord | None = None
    error: str = ""
    changed: dict[str, Any] = field(default_factory=dict)


def enroll(
    name: str,
    address: str,
    config: Config | None = None,
    *,
    port: int = 22,
    user: str | None = None,
    expect_fingerprint: str | None = None,
    accept_identity_change: bool = False,
    notes: str = "",
) -> EnrollResult:
    """Record a target's trusted identity from a live endpoint.

    Enrolment is the only operation allowed to *learn* a key. It still refuses to replace an
    existing record without ``accept_identity_change``, and ``expect_fingerprint`` permits
    out-of-band confirmation so the key never has to be trusted blindly.
    """
    from .targets import Target

    previous = load_record(name, config)
    observed = _ssh_keyscan(address, port)
    if not observed:
        return EnrollResult(False, error=f"no SSH host key could be read from {address}:{port}")

    observed_set = {d.get("fingerprint", "") for d in observed.values() if d.get("fingerprint")}
    if expect_fingerprint and expect_fingerprint not in observed_set:
        return EnrollResult(
            False,
            error=(f"{address} presented {sorted(observed_set)}, which does not include the "
                   f"expected {expect_fingerprint}; refusing to enrol"),
        )

    if previous and previous.ssh_keys:
        relation = compare_keys(previous.ssh_keys, observed)
        if relation != "match" and not accept_identity_change:
            return EnrollResult(
                False,
                error=(f"{name} is already enrolled with different host keys "
                       f"({relation}); re-enrolment requires explicit authorisation"),
                changed={"previous": previous.fingerprints(),
                         "observed": {a: d.get("fingerprint", "") for a, d in observed.items()}},
            )

    record = IdentityRecord(
        name=name,
        enrolled_at=previous.enrolled_at if previous else time.time(),
        updated_at=time.time(),
        ssh_keys=observed,
        observations=list(previous.observations) if previous else [],
        endpoints=list(previous.endpoints) if previous else [],
        notes=notes or (previous.notes if previous else ""),
    )

    # Hardware observations are best-effort and never block enrolment: an unreadable DMI or a
    # missing machine-id must not make a target unenrollable.
    probe_target = Target(name=name, transport="ssh", host=address, user=user, port=port,
                          ssh_timeout=30.0)
    entry = Endpoint(address=address, port=port, role="management", verified=True,
                     first_seen=time.time(), last_seen=time.time(), note="enrolled")
    record.endpoints = [e for e in record.endpoints if e.address != address] + [entry]

    # The managed known_hosts is written before any authenticated SSH, so the enrolment probe
    # itself is verified against exactly the keys just recorded instead of trusting blind.
    write_managed_known_hosts(record, config)
    raw = _probe_hardware(probe_target)
    if raw:
        record.observations = build_observations(raw, config)
        record.notes = record.notes or ""
        for extra in management_addresses(raw):
            if extra != address and all(e.address != extra for e in record.endpoints):
                record.endpoints.append(
                    Endpoint(address=extra, port=port, role="management", verified=False,
                             last_seen=time.time(), note="reported by the target itself")
                )

    save_record(record, config)
    write_managed_known_hosts(record, config)
    return EnrollResult(True, record=record)


# -------------------------------------------------------------------------- refresh

@dataclass
class RefreshResult:
    status: str
    current: str | None = None
    proposed: str | None = None
    record: IdentityRecord | None = None
    discovery: DiscoveryResult | None = None
    error: str = ""
    applied: bool = False


def reenroll_required(record: IdentityRecord, relation: str) -> bool:
    return relation in ("rotated", "partial", "mismatch")


def refresh(
    name: str,
    config: Config | None = None,
    *,
    apply: bool = False,
    address: str | None = None,
    subnets: Iterable[str] | None = None,
    port: int = 22,
) -> RefreshResult:
    """Verify the current endpoint, and optionally resolve and persist a new one.

    Resolving never persists: ``apply`` is a separate decision, and when it is taken only the
    target's ``host`` field is rewritten, so unrelated configuration is untouched.
    """
    from . import targets as targets_core  # noqa: F401 - kept for symmetry with discover

    record = load_record(name, config)
    if record is None:
        return RefreshResult(status="not-enrolled",
                             error=f"{name} has no identity record; run 'caasi target enroll'")

    target = targets_core.find_target(config or Config({}, []), name)
    current = address or (target.host if target else None)

    if current:
        relation, observed = verify_address(record, current, port)
        if relation == "match":
            record.endpoints = [e for e in record.endpoints if e.address != current] + [
                Endpoint(address=current, port=port, role="management", verified=True,
                         first_seen=time.time(), last_seen=time.time())
            ]
            write_managed_known_hosts(record, config)
            save_record(record, config)
            return RefreshResult(status="current-verified", current=current, record=record)
        if reenroll_required(record, relation):
            return RefreshResult(
                status="conflict", current=current, record=record,
                error=(f"{current} presents host keys that do not match the enrolled identity "
                       f"({relation}); refusing to use it. If the machine was reinstalled or "
                       f"replaced, re-enrol explicitly."),
            )

    result = discover(record, config, subnets=subnets, port=port)
    if result.status != VERIFIED:
        return RefreshResult(status=result.status, current=current, record=record,
                             discovery=result,
                             error=result.error or _explain(result))

    proposed = result.verified[0].address
    applied = False
    if apply:
        applied = persist_endpoint(name, proposed, config, port=port)
    record.endpoints = [e for e in record.endpoints if e.address != proposed] + [
        Endpoint(address=proposed, port=port, role="management", verified=True,
                 first_seen=time.time(), last_seen=time.time(),
                 note="discovered" + (" and applied" if applied else ""))
    ]
    write_managed_known_hosts(record, config)
    save_record(record, config)
    return RefreshResult(status="endpoint-found", current=current, proposed=proposed,
                         record=record, discovery=result, applied=applied)


def _explain(result: DiscoveryResult) -> str:
    if result.status == NO_CANDIDATES:
        return (f"scanned {result.scanned} addresses on {', '.join(result.subnets)} and found "
                f"no SSH host; the target may be offline or on another network")
    if result.status == AMBIGUOUS:
        return (f"{len(result.verified)} addresses present the enrolled key "
                f"({', '.join(c.address for c in result.verified)}); this looks like a "
                f"cloned image and was not resolved automatically")
    if result.status == CONFLICT:
        return "a reachable host presents different host keys than the enrolled identity"
    return "no reachable address presented the enrolled host key"


def persist_endpoint(
    name: str,
    address: str,
    config: Config | None = None,
    *,
    port: int = 22,
) -> bool:
    """Write only ``targets.<name>.host`` (and ``port`` when non-default).

    Deliberately narrow: refreshing an address must not rewrite unrelated settings such as
    tags, timeouts, capability declarations or deployment roots.
    """
    from .config import global_config_path

    cfg = config
    if cfg is None:
        return False
    targets_map = cfg.get("targets")
    if not isinstance(targets_map, dict) or name not in targets_map:
        return False
    spec = targets_map.get(name)
    if not isinstance(spec, dict):
        return False
    if spec.get("host") == address and (port == 22 or spec.get("port") == port):
        return False
    spec["host"] = address
    if port != 22:
        spec["port"] = port
    cfg.save(global_config_path())
    return True
