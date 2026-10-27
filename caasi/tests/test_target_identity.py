"""Stable target identity: trust records, verification, bounded discovery, re-enrolment.

Every test runs against controlled fixtures — no robot, no real network. The SSH/keyscan
boundaries are injected, so what is asserted is the decision logic: which address may be
trusted, when a conflict is reported, and what discovery is permitted to touch.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import identity
from caasi.core.config import Config
from caasi.core.targets import Target, target_ssh_prefix

runner = CliRunner()

MANAGEMENT_MAC = "bc:fd:0c:c2:56:81"
LIDAR_MAC = "68:1d:ef:5a:d1:93"


def _keys(*fingerprints: str) -> dict[str, dict[str, str]]:
    """A key set as ssh-keyscan would report it."""
    out = {}
    for index, fp in enumerate(fingerprints):
        algo = "ssh-ed25519" if index == 0 else f"ssh-rsa{index}"
        out[algo] = {"public": f"PUBLIC{index}-{fp}", "fingerprint": fp}
    return out


ENROLLED = _keys("SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
ROTATED = _keys("SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Isolated identity storage and config, so nothing touches the real ~/.caasi."""
    monkeypatch.setattr(identity, "identity_root", lambda config=None: tmp_path / "identity")
    yield tmp_path


@pytest.fixture
def enrolled(store):
    record = identity.IdentityRecord(
        name="swjtumover05",
        enrolled_at=1.0,
        updated_at=1.0,
        ssh_keys=ENROLLED,
        observations=[
            identity.Observation("machine_id", "2c7c442a1da8", "probe:/etc/machine-id", "strong"),
            identity.Observation("mac.management", MANAGEMENT_MAC,
                                 "probe:/sys/class/net/wlp2s0/address", "strong"),
            identity.Observation("mac.internal", LIDAR_MAC,
                                 "probe:/sys/class/net/enp1s0/address", "strong"),
        ],
        endpoints=[identity.Endpoint("10.212.19.94", 22, "management", verified=True)],
    )
    identity.save_record(record)
    identity.write_managed_known_hosts(record)
    return record


def _cfg(tmp_path, host="10.212.19.94", subnets=None, extra=None):
    """A config object backed by a temp file, mirroring the real target config shape."""
    targets = {"swjtumover05": {"host": host, "user": "swjtumover",
                                "tags": ["robot", "wifi"], "ssh_timeout": 30.0}}
    data = {"targets": targets}
    if subnets is not None:
        data["discovery"] = {"subnets": subnets}
    if extra:
        data.update(extra)
    return Config(data, [])


# ------------------------------------------------------------------ IP change, same key

def test_endpoint_change_with_the_same_key_is_accepted(enrolled, monkeypatch):
    """The whole point: a new address presenting the enrolled key is the same robot."""
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (True, 1.0))
    assert result.status in (identity.AMBIGUOUS, identity.VERIFIED)
    assert all(c.relation == "match" for c in result.candidates)


def test_verify_address_reports_match_for_enrolled_key(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    relation, _ = identity.verify_address(enrolled, "10.212.19.94")
    assert relation == "match"


def test_new_host_key_at_a_known_address_is_a_conflict_not_a_match(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    relation, observed = identity.verify_address(enrolled, "10.212.19.94")
    assert relation in ("rotated", "mismatch")
    assert observed, "the observed keys must be reported so the change is auditable"


def test_refresh_refuses_a_host_key_conflict(enrolled, monkeypatch, store):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    result = identity.refresh("swjtumover05", _cfg(store))
    assert result.status == "conflict"
    assert "reinstall" in result.error.lower() or "re-enrol" in result.error.lower()


# --------------------------------------------------------------------- re-enrolment

def test_reenrolment_requires_explicit_authorisation(enrolled):
    result = identity.enroll("swjtumover05", "10.212.19.99", None,
                             accept_identity_change=False)
    # Keys at the new address are read first; here they are unavailable, which also refuses.
    assert result.ok is False


def test_reenrolment_replaces_keys_only_when_authorised(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    monkeypatch.setattr(identity, "_probe_hardware", lambda target: {})

    refused = identity.enroll("swjtumover05", "10.212.19.94", None)
    assert refused.ok is False and "explicit" in refused.error.lower()
    assert identity.load_record("swjtumover05").ssh_keys == ENROLLED

    allowed = identity.enroll("swjtumover05", "10.212.19.94", None,
                              accept_identity_change=True)
    assert allowed.ok is True
    assert identity.load_record("swjtumover05").ssh_keys == ROTATED


def test_expected_fingerprint_permits_out_of_band_confirmation(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    monkeypatch.setattr(identity, "_probe_hardware", lambda target: {})
    good = list(ROTATED.values())[0]["fingerprint"]
    assert identity.enroll("swjtumover05", "10.212.19.94", None,
                           expect_fingerprint=good, accept_identity_change=True).ok
    bad = identity.enroll("swjtumover05", "10.212.19.94", None,
                          expect_fingerprint="SHA256:not-there",
                          accept_identity_change=True)
    assert bad.ok is False and "expected" in bad.error


# ------------------------------------------------------- offline vs nothing found

def test_discovery_not_configured_is_not_reported_as_offline(enrolled):
    result = identity.discover(enrolled, None)
    assert result.status == identity.NOT_CONFIGURED
    assert "not an offline target" in result.error


def test_scan_without_any_live_host_reports_no_candidates(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan", lambda *a, **k: {})
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (False, None))
    assert result.status == identity.NO_CANDIDATES
    assert result.scanned > 0 and result.live == 0


def test_live_host_with_unrelated_keys_reports_no_match(enrolled, monkeypatch):
    """A different machine entirely: different algorithm, so no overlap with the record."""
    unrelated = {"ssh-ecdsa": {"public": "PUB-ECDSA", "fingerprint": "SHA256:ECDSA"}}
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: unrelated)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (True, 1.0))
    assert result.status == identity.NO_MATCH
    assert result.candidates and all(c.relation != "match" for c in result.candidates)


def test_same_algorithm_with_new_material_at_the_known_address_is_a_conflict(enrolled, monkeypatch):
    """Key rotation on the same algorithm is a conflict, not a benign "not found"."""
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (True, 1.0),
                               current="10.212.19.1")
    assert result.status == identity.CONFLICT


def test_stranger_on_the_subnet_is_not_our_targets_conflict(enrolled, monkeypatch):
    """Another machine answering with its own keys must not read as our identity conflict."""
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (True, 1.0),
                               current="10.212.19.94")
    assert result.status == identity.NO_MATCH


def test_two_addresses_with_the_enrolled_key_is_ambiguous(enrolled, monkeypatch):
    """A cloned image must not be resolved by silently picking one address."""
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/29"],
                               connect=lambda a, p, t: (True, 1.0))
    assert result.status == identity.AMBIGUOUS
    assert len(result.verified) >= 2


def test_a_single_verified_candidate_is_resolved(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    result = identity.discover(enrolled, None, subnets=["10.212.19.0/30"],
                               connect=lambda a, p, t: (a.endswith(".1"), 1.0))
    assert result.status == identity.VERIFIED
    assert [c.address for c in result.verified] == ["10.212.19.1"]


# ------------------------------------------------------------- endpoint persistence

def test_refresh_does_not_persist_without_apply(enrolled, monkeypatch, store):
    cfg = _cfg(store, host="10.212.19.94", subnets=["10.212.19.0/30"])
    # The old address is gone; the robot answers at .1 with the enrolled key.
    monkeypatch.setattr(
        identity, "_ssh_keyscan",
        lambda address, port=22, timeout=2.0: ENROLLED if address.endswith(".1") else {})
    from caasi.core import targets as targets_core
    monkeypatch.setattr(targets_core, "check_socket_reachable",
                        lambda address, port=22, timeout=1.5: (address.endswith(".1"), 1.0))
    result = identity.refresh("swjtumover05", cfg, apply=False,
                              subnets=["10.212.19.0/30"])
    assert result.proposed == "10.212.19.1"
    assert result.applied is False
    assert cfg.get("targets.swjtumover05.host") == "10.212.19.94", "config must be untouched"


def test_apply_writes_only_the_host_field(enrolled, monkeypatch, store):
    cfg = _cfg(store, extra={"discovery": {"subnets": ["10.212.19.0/30"]}})
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    monkeypatch.setattr(type(cfg), "save", lambda self, path=None: None)
    before = json.loads(json.dumps(cfg.data))
    changed = identity.persist_endpoint("swjtumover05", "10.212.19.1", cfg)
    assert changed is True
    assert cfg.get("targets.swjtumover05.host") == "10.212.19.1"
    # everything else identical: tags, timeout, user, and the discovery settings
    after = cfg.data["targets"]["swjtumover05"]
    assert after["tags"] == before["targets"]["swjtumover05"]["tags"]
    assert after["ssh_timeout"] == before["targets"]["swjtumover05"]["ssh_timeout"]
    assert after["user"] == before["targets"]["swjtumover05"]["user"]
    assert cfg.data["discovery"] == before["discovery"]


def test_persist_endpoint_ignores_unknown_target(enrolled, store):
    cfg = _cfg(store)
    assert identity.persist_endpoint("not-a-target", "10.0.0.1", cfg) is False


# --------------------------------------------------- identifiers and classification

def test_unusable_identifiers_are_not_recorded_as_identity():
    """Generic SMBIOS strings and hidden serials carry no information (measured on the robot)."""
    raw = {
        "machine_id": "2c7c442a1da8",
        "hostname": "swjtumover05",
        "cpu_model": "Intel(R) N150",
        "arch": "x86_64",
        "dmi": {"sys_vendor": "Default string", "product_name": "Default string",
                "product_serial": "", "product_uuid": "None"},
        "interfaces": [{"name": "wlp2s0", "mac": MANAGEMENT_MAC, "default_route": True,
                        "addresses": ["10.212.19.94"]}],
    }
    fields = {o.field for o in identity.build_observations(raw)}
    assert "dmi.product_serial" not in fields
    assert "dmi.sys_vendor" not in fields
    assert "machine_id" in fields and "mac.management" in fields


def test_internal_macs_of_identical_robots_stay_distinct():
    """Two robots of the same model must not collapse onto one observation."""
    raw = {"interfaces": [
        {"name": "enp1s0", "mac": "68:1d:ef:5a:d1:93", "default_route": False,
         "addresses": ["192.168.110.10"]},
        {"name": "enp3s0", "mac": "68:1d:ef:5a:d1:94", "default_route": False,
         "addresses": ["192.168.100.10"]},
    ]}
    fields = {o.field for o in identity.build_observations(raw)}
    assert "mac.internal.enp1s0" in fields and "mac.internal.enp3s0" in fields


def test_missing_machine_id_does_not_break_enrolment(store, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ENROLLED)
    monkeypatch.setattr(identity, "_probe_hardware",
                        lambda target: {"machine_id": "", "interfaces": []})
    result = identity.enroll("partial-bot", "10.212.19.50", None)
    assert result.ok is True
    assert all(o.field != "machine_id" for o in result.record.observations)


def test_management_and_internal_interfaces_are_classified():
    """A robot's LiDAR/motor links must never be offered as a management endpoint."""
    raw = {"interfaces": [
        {"name": "wlp2s0", "mac": MANAGEMENT_MAC, "default_route": True,
         "addresses": ["10.212.19.94"]},
        {"name": "enp1s0", "mac": LIDAR_MAC, "default_route": False,
         "addresses": ["192.168.110.10"]},
        {"name": "enp3s0", "mac": "68:1d:ef:5a:d1:94", "default_route": False,
         "addresses": ["192.168.100.10"]},
    ]}
    assert identity.management_addresses(raw) == ["10.212.19.94"]
    fields = {o.field: o.value for o in identity.build_observations(raw)}
    assert fields["mac.management"] == MANAGEMENT_MAC
    assert fields["address.management"] == "10.212.19.94"
    # Internal NICs are recorded per interface, never as a candidate endpoint.
    assert fields["mac.internal.enp1s0"] == LIDAR_MAC
    assert fields["address.internal.enp1s0"] == "192.168.110.10"
    assert fields["address.internal.enp3s0"] == "192.168.100.10"
    assert all(v != "192.168.110.10" for k, v in fields.items()
               if k.startswith("address.management"))


def test_key_relation_distinguishes_rotation_from_a_different_machine():
    two = _keys("SHA256:AAAA", "SHA256:BBBB")
    assert identity.compare_keys(two, two) == "match"
    rotated = _keys("SHA256:CCCC", "SHA256:DDDD")
    assert identity.compare_keys(two, rotated) == "rotated"
    partial = dict(two)
    partial[sorted(two)[0]] = {"public": "different", "fingerprint": "SHA256:X"}
    assert identity.compare_keys(two, partial) == "partial"
    assert identity.compare_keys(two, {}) == "mismatch"


# ------------------------------------------------------------------- scan bounds

def test_subnet_larger_than_the_cap_is_refused_not_truncated(enrolled):
    result = identity.discover(enrolled, None, subnets=["10.0.0.0/16"], max_hosts=256)
    assert result.status == identity.SCAN_FAILED
    assert "cap is 256" in result.error


def test_scan_covers_a_configured_small_subnet_fully(enrolled, monkeypatch):
    seen = []
    monkeypatch.setattr(identity, "_ssh_keyscan", lambda *a, **k: {})
    identity.discover(enrolled, None, subnets=["10.212.19.0/29"], max_hosts=256,
                      connect=lambda a, p, t: (seen.append(a), (False, None))[1])
    assert len(seen) == 6, "a /29 has six usable host addresses"


def test_scan_stops_at_the_total_cap_across_subnets(enrolled, monkeypatch):
    seen = []
    monkeypatch.setattr(identity, "_ssh_keyscan", lambda *a, **k: {})
    identity.discover(enrolled, None,
                      subnets=["10.212.19.0/29", "10.212.20.0/29", "10.212.21.0/29"],
                      max_hosts=10,
                      connect=lambda a, p, t: (seen.append(a), (False, None))[1])
    assert len(seen) == 10


def test_invalid_subnet_is_reported(enrolled):
    result = identity.discover(enrolled, None, subnets=["not-a-subnet"])
    assert result.status == identity.SCAN_FAILED
    assert "invalid subnet" in result.error


def test_scan_never_exceeds_the_configured_subnets(enrolled, monkeypatch):
    seen = []
    monkeypatch.setattr(identity, "_ssh_keyscan", lambda *a, **k: {})
    identity.discover(enrolled, _cfg("/tmp", subnets=["10.212.19.0/29"]),
                      connect=lambda a, p, t: (seen.append(a), (False, None))[1])
    assert all(a.startswith("10.212.19.") for a in seen)


# ------------------------------------------------------- SSH verification everywhere

def test_enrolled_target_uses_strict_host_key_checking(enrolled):
    prefix = target_ssh_prefix(
        Target(name="swjtumover05", transport="ssh", host="10.212.19.94", user="swjtumover"))
    assert "StrictHostKeyChecking=yes" in prefix
    assert "StrictHostKeyChecking=accept-new" not in prefix
    assert "StrictHostKeyChecking=no" not in prefix
    known_hosts = [a for a in prefix if a.startswith("UserKnownHostsFile=")]
    assert known_hosts and str(identity.identity_root()) in known_hosts[0]


def test_target_without_a_record_keeps_previous_behaviour(store):
    prefix = target_ssh_prefix(
        Target(name="legacy-bot", transport="ssh", host="10.0.0.5", user="robot"))
    assert "StrictHostKeyChecking=accept-new" in prefix
    assert "StrictHostKeyChecking=no" not in prefix


def test_managed_known_hosts_matches_the_enrolled_fingerprints(enrolled):
    path = identity.write_managed_known_hosts(enrolled)
    text = path.read_text()
    assert all(data["public"] in text for data in ENROLLED.values())
    assert "10.212.19.94" in text


def test_known_hosts_follows_the_endpoint_after_a_change(enrolled):
    enrolled.endpoints.append(identity.Endpoint("10.212.19.94", 22, "management",
                                                verified=True))
    enrolled.endpoints.append(identity.Endpoint("10.212.19.120", 22, "management",
                                                verified=True))
    text = identity.write_managed_known_hosts(enrolled).read_text()
    assert "10.212.19.94" in text and "10.212.19.120" in text


# ----------------------------------------------------------------- CLI behaviour

def test_cli_discover_exit_code_separates_unconfigured_from_not_found(enrolled):
    result = runner.invoke(app, ["target", "discover", "swjtumover05", "--json"])
    # No discovery.subnets in the default config -> "cannot run", exit 3.
    assert result.exit_code == 3


def test_cli_identity_reports_missing_record(store):
    result = runner.invoke(app, ["target", "identity", "unknown-bot"])
    assert result.exit_code == 1
    assert "no identity record" in result.output


def test_cli_reenroll_requires_the_flag(enrolled, monkeypatch):
    monkeypatch.setattr(identity, "_ssh_keyscan",
                        lambda address, port=22, timeout=2.0: ROTATED)
    result = runner.invoke(app, ["target", "reenroll", "swjtumover05", "--host",
                                 "10.212.19.94"])
    assert result.exit_code == 1
    assert "accept-identity-change" in result.output


def test_backwards_compatible_config_without_identity_fields(store):
    """An existing config with no identity section must keep working unchanged."""
    cfg = _cfg(store)
    target = Target(name="swjtumover05", transport="ssh", host="10.212.19.94",
                    user="swjtumover", tags=["robot", "wifi"], ssh_timeout=30.0)
    assert target.ssh_timeout == 30.0
    assert identity.load_record("swjtumover05") is None
    prefix = target_ssh_prefix(target)
    assert "StrictHostKeyChecking=accept-new" in prefix
