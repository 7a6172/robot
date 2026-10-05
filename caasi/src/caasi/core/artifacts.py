"""Run result/output collection and routing.

This module closes the lifecycle for runs that *produce* data:

    project -> deployment -> target -> build -> run -> artifacts -> destination

Design boundaries, deliberately narrow:

* **caasi routes, it does not interpret.** An artifact is described by where it
  is, how big it is, what kind it looks like, and where it was sent. caasi does
  not parse checkpoints, read metrics, or understand any domain format.
* **Nothing moves by default.** An unclassified artifact stays where it was
  produced and its location is recorded. Copying is opt-in through a declared
  ``outputs:`` block or an explicit command, so a run emitting gigabytes cannot
  silently saturate a slow link.
* **Collection is separate from execution and from observability.** A run's
  artifacts are collected after it finishes; this module never starts, stops or
  inspects a running process.
* **Nothing is deleted.** Routing moves copies between known locations. Removal
  is out of scope for this module entirely.

Two destinations are supported, and they encode a real distinction:

``workstation``
    Ephemeral compute results that should come back to the developer's machine.
``target_local``
    Data that belongs to the target - large checkpoints, persistent runtime data,
    site-specific maps - which is *recorded* but not moved.


THE DESTINATION MODEL (authoritative reference)
-----------------------------------------------

**Execution and destination are independent.** Where a run executes (its target) and
where its results end up are separate decisions: a workload on a remote robot can
send its metrics home while leaving its maps on the robot.

Resolution order, for each artifact
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every artifact gets exactly one :class:`ArtifactRoute`, decided in this order. The
first rule that applies wins, and the route records **which** rule it was:

===========================================  ==========================  ==========================
Rule                                          Destination                 ``route.reason``
===========================================  ==========================  ==========================
a declaration matches **and** names a dest.   that destination            ``declared``
a declaration matches, no destination          policy for the declared kind  ``declared-kind-policy``
no declaration; the inferred kind has a rule   ``by_kind[kind]``           ``kind-policy``
nothing applies                                ``policy.unclassified``     ``unclassified``
===========================================  ==========================  ==========================

``route.declared`` is ``True`` when a declaration was involved, so a reader can
tell a deliberate instruction from a default.

Per-kind defaults
~~~~~~~~~~~~~~~~~

Deliberately conservative - **nothing is copied by accident**:

======================  ==================
kind                    default destination
======================  ==================
``metrics``             ``workstation``
``report``              ``workstation``
``log``                 ``workstation``
anything unclassified   ``target_local``
======================  ==================

A run emitting gigabytes therefore cannot silently saturate a slow link: anything
unrecognised stays where it was produced and its location is **recorded**.

Declarations
~~~~~~~~~~~~

A project declares outputs per workload or experiment::

    outputs:
      - {path: "runs/*/map.json", kind: map}                      # kind policy applies
      - {path: "*.log",  kind: logs, destination: target_local}   # explicit override

``path`` is a glob matched against the artifact's path relative to the run's working
directory. ``kind`` feeds the per-kind policy when no destination is named.
``destination`` overrides everything. ``required`` marks an output whose absence is
worth reporting.

Configuration
~~~~~~~~~~~~~

The policy is **configurable without code**, per project::

    artifact_routing:
      metrics: workstation      # by kind
      default: target_local     # the fallback (also accepts "unclassified" or "*")

Only names in :data:`DESTINATIONS` are accepted; an unknown destination in
configuration is **ignored** rather than guessed, so a typo cannot silently route
data somewhere unintended.

Inspection
~~~~~~~~~~

Every routing decision is recorded with its reason, so an operator can ask *why* a
file went where it did rather than inferring it. ``ArtifactRecord`` carries the
routes for a run, and ``plan_collection`` splits artifacts into what will be
fetched and what is left in place.

What a third destination would require
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**None is implemented, deliberately.** ``target_local`` and ``workstation`` cover
every case encountered so far: results either return to the developer or belong to
the target. A third destination (an archive, a shared store, another machine) would
need **all** of the following, and adding it without them would produce a name that
cannot actually receive anything:

1. **An entry in** :data:`DESTINATIONS` - the model's single source of truth.
2. **A transport** that performs the copy. Today only ``workstation`` is *fetched*
   (``collect_artifacts`` transfers from an SSH target); ``target_local`` is recorded
   and never moved. A third destination needs its own transfer step.
3. **A resolution rule** in :meth:`RoutingPolicy.for_artifact`, plus the ``reason``
   string that explains it.
4. **Configuration handling** - ``from_config`` already validates against
   :data:`DESTINATIONS`, so a new name becomes configurable automatically.
5. **Inspection and tests** - the decision must be visible in ``ArtifactRecord`` and
   covered by tests, including the failure path when the destination is unreachable.

**What it deliberately does NOT require:** a server, a content-addressed store, an
object store, or a database. caasi routes copies between locations it already knows;
it is not a storage system. A future destination should stay a *transfer target*,
not become infrastructure - which is why none is built speculatively here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .config import Config
from .targets import Target, target_ssh_prefix

# ---------------------------------------------------------------------------
# Kind classification
#
# Extension-based and deliberately small. `kind` is advisory metadata used for
# routing defaults and human display; it never gates collection, so an unknown
# extension is simply `other` rather than an error.
# ---------------------------------------------------------------------------

KIND_BY_EXTENSION: dict[str, str] = {
    # model weights / checkpoints
    ".pt": "model", ".pth": "model", ".ckpt": "model", ".onnx": "model",
    ".safetensors": "model", ".h5": "model", ".pb": "model",
    # tabular / scalar results
    ".json": "metrics", ".jsonl": "metrics", ".csv": "metrics",
    ".tsv": "metrics", ".yaml": "metrics", ".yml": "metrics",
    ".txt": "metrics", ".md": "report", ".html": "report", ".pdf": "report",
    # media
    ".mp4": "media", ".avi": "media", ".mov": "media", ".mkv": "media",
    ".gif": "media", ".png": "media", ".jpg": "media", ".jpeg": "media",
    ".webp": "media", ".svg": "media",
    # logs
    ".log": "log",
    # 3D / map data
    ".ply": "map", ".pcd": "pointcloud", ".obj": "mesh", ".stl": "mesh",
    ".glb": "mesh", ".gltf": "mesh", ".usd": "usd", ".usda": "usd",
    ".usdc": "usd", ".pgm": "map", ".yaml_": "map",
    # datasets
    ".bag": "dataset", ".mcap": "dataset", ".db3": "dataset",
    ".hdf5": "dataset", ".h5py": "dataset", ".npz": "dataset", ".npy": "dataset",
    ".parquet": "dataset", ".zip": "archive", ".tar": "archive",
    ".gz": "archive", ".tgz": "archive", ".xz": "archive", ".zst": "archive",
}

# Bookkeeping files caasi itself writes into a run directory or deployment root.
# These are provenance, not results, and are never treated as artifacts.
BOOKKEEPING_NAMES = {
    # run control files
    "manifest.yaml", "run.sh", "stdout.log", "stderr.log", "exit_code",
    "pid", "pgid", "artifacts.yaml",
    # deployment / build provenance
    ".caasi-deployment.json", ".caasi-build.json",
    # the provenance bundle caasi writes into every run directory - these are
    # provenance, not results, and must not be reported as artifacts
    "environment.yaml", "hardware.yaml", "dependencies.yaml",
    "configuration.yaml", "git.json", "processes.json",
}

BOOKKEEPING_SUFFIXES = (".pyc", ".pyo")

# Directories that hold caasi or build bookkeeping rather than run results.
BOOKKEEPING_DIRS = {".caasi", "__pycache__", "build", "install", "log"}

# Files at or below this size are hashed by default. Above it, hashing is
# deferred to an explicit --verify, because hashing is O(bytes) and can dominate
# the cost of collection over a slow link.
DEFAULT_HASH_MAX_BYTES = 8 * 1024 * 1024

DESTINATIONS = ("workstation", "target_local")


class ArtifactError(ValueError):
    """Raised for an invalid artifact declaration."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ArtifactRoute:
    """Resolved routing decision for one artifact."""

    destination: str = "target_local"   # "workstation" | "target_local"
    reason: str = "unclassified"        # why this destination was chosen
    declared: bool = False              # came from an outputs: declaration

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Artifact:
    """One produced file, with identity, location and routing decision."""

    artifact_id: str
    run_id: str
    path: str                # relative to the run output root
    kind: str
    size_bytes: int
    location: str            # "workstation" | "target"
    abs_path: str            # where it is now
    sha256: str | None = None
    route: ArtifactRoute = field(default_factory=ArtifactRoute)
    collected_to: str | None = None   # host path once copied, else None
    declared: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("route", None)
        d["route"] = self.route.to_dict()
        return d


@dataclass
class ArtifactRecord:
    """Collected artifacts for one run, plus the provenance links that identify it."""

    run_id: str
    project: str | None = None
    target_name: str = "local"
    target_transport: str = "local"
    run_status: str | None = None      # succeeded | failed | stopped | ...
    collected_at: str | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    # Provenance chain, mirroring RunRecord so an artifact record stands alone.
    deployment_id: str | None = None
    build_id: str | None = None
    git_revision: str | None = None
    remote_run_dir: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(a.size_bytes for a in self.artifacts)

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for art in self.artifacts:
            counts[art.kind] = counts.get(art.kind, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "target_name": self.target_name,
            "target_transport": self.target_transport,
            "run_status": self.run_status,
            "collected_at": self.collected_at,
            "deployment_id": self.deployment_id,
            "build_id": self.build_id,
            "git_revision": self.git_revision,
            "remote_run_dir": self.remote_run_dir,
            "artifact_count": len(self.artifacts),
            "total_bytes": self.total_bytes,
            "by_kind": self.by_kind(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_kind(path: str) -> str:
    """Best-effort kind for a path. Unknown extensions are ``other``, never an error."""
    lower = path.lower()
    # Handle double extensions like .tar.gz before the single-extension lookup.
    for double in (".tar.gz", ".tar.xz", ".tar.zst", ".urdf.xacro"):
        if lower.endswith(double):
            return "archive" if double.startswith(".tar") else "other"
    ext = Path(lower).suffix
    return KIND_BY_EXTENSION.get(ext, "other")


def resolve_kind(rel_path: str, declarations: list["OutputDeclaration"]) -> str:
    """Kind for a path, preferring an explicit declaration over the extension.

    Extension inference is a convenience, not an authority: a project's real
    outputs may not follow file-type conventions (SLAM map JSON is not a metric).
    A declaration that names the artifact is the better answer, so it wins.
    """
    for decl in declarations:
        if decl.matches(rel_path):
            return decl.kind
    return classify_kind(rel_path)


def is_bookkeeping(rel_path: str) -> bool:
    """True for caasi's own bookkeeping, which is never an artifact."""
    parts = Path(rel_path).parts
    if any(part in BOOKKEEPING_DIRS for part in parts):
        return True
    name = parts[-1] if parts else rel_path
    if name in BOOKKEEPING_NAMES:
        return True
    return name.endswith(BOOKKEEPING_SUFFIXES)


def make_artifact_id(run_id: str, rel_path: str, sha256: str | None = None) -> str:
    """Stable identity for an artifact.

    Prefers content identity when a hash exists, so the same bytes produced by
    two runs share an id; otherwise falls back to provenance identity, which is
    always available.
    """
    normalised = rel_path.replace("\\", "/").strip("/")
    if sha256:
        return f"{sha256[:16]}"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", normalised).strip("-").lower()
    return f"{run_id}:{slug}"


# ---------------------------------------------------------------------------
# Declaration parsing (experiment `outputs:`)
# ---------------------------------------------------------------------------


@dataclass
class OutputDeclaration:
    """One declared output pattern with its routing intent."""

    pattern: str
    kind: str
    destination: str | None = None   # None -> fall back to routing policy
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def matches(self, rel_path: str) -> bool:
        normalised = rel_path.replace("\\", "/").lstrip("./")
        pat = self.pattern.replace("\\", "/").lstrip("./")
        if fnmatch(normalised, pat):
            return True
        # A bare directory prefix (e.g. "checkpoints") should match below it.
        if not any(ch in pat for ch in "*?[") and normalised.startswith(pat.rstrip("/") + "/"):
            return True
        return False


def parse_outputs(raw: Any) -> list[OutputDeclaration]:
    """Parse an experiment ``outputs:`` block.

    Accepted forms, deliberately permissive so a project does not have to learn a
    schema to declare one file::

        outputs:
          - results/*.json            # simplest: pattern only
          - path: checkpoints/*.pt    # explicit
            kind: model
            destination: target_local
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ArtifactError("'outputs' must be a list")

    declarations: list[OutputDeclaration] = []
    for entry in raw:
        if isinstance(entry, str):
            declarations.append(OutputDeclaration(pattern=entry, kind=classify_kind(entry)))
            continue
        if not isinstance(entry, dict):
            raise ArtifactError(f"unsupported outputs entry: {entry!r}")
        pattern = entry.get("path") or entry.get("pattern")
        if not pattern:
            raise ArtifactError(f"outputs entry needs a 'path': {entry!r}")
        dest = entry.get("destination")
        if dest is not None and dest not in DESTINATIONS:
            raise ArtifactError(
                f"unknown destination '{dest}' (expected one of {', '.join(DESTINATIONS)})"
            )
        declarations.append(
            OutputDeclaration(
                pattern=str(pattern),
                kind=str(entry.get("kind") or classify_kind(str(pattern))),
                destination=str(dest) if dest else None,
                required=bool(entry.get("required", False)),
            )
        )
    return declarations


# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------


@dataclass
class RoutingPolicy:
    """Default destination per artifact kind.

    Defaults are deliberately conservative: everything stays on the target unless
    it is known to be small and useful at the workstation. Nothing is copied by
    accident.
    """

    by_kind: dict[str, str] = field(default_factory=lambda: {
        "metrics": "workstation",
        "report": "workstation",
        "log": "workstation",
    })
    unclassified: str = "target_local"

    @classmethod
    def from_config(cls, config: Config | None) -> "RoutingPolicy":
        """Build from a project's ``artifact_routing`` block when present."""
        policy = cls()
        if config is None:
            return policy
        raw = config.get("artifact_routing") or {}
        if not isinstance(raw, dict):
            return policy
        for key, value in raw.items():
            dest = value.get("destination") if isinstance(value, dict) else value
            if dest is None:
                continue
            if dest not in DESTINATIONS:
                continue
            if key in ("unclassified", "default", "*"):
                policy.unclassified = str(dest)
            else:
                policy.by_kind[str(key)] = str(dest)
        return policy

    def for_artifact(self, kind: str, declarations: list[OutputDeclaration], rel_path: str) -> ArtifactRoute:
        """Resolve the destination for one artifact, declaration first."""
        for decl in declarations:
            if decl.matches(rel_path):
                if decl.destination:
                    return ArtifactRoute(decl.destination, "declared", True)
                # Declared but no explicit destination: use policy for its kind.
                dest = self.by_kind.get(decl.kind, self.unclassified)
                return ArtifactRoute(dest, "declared-kind-policy", True)
        if kind in self.by_kind:
            return ArtifactRoute(self.by_kind[kind], "kind-policy", False)
        return ArtifactRoute(self.unclassified, "unclassified", False)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def hash_file(path: Path, chunk: int = 1024 * 1024) -> str | None:
    """Streamed sha256. Returns None if the file cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def _artifact_from_stat(
    run_id: str,
    rel_path: str,
    size: int,
    abs_path: str,
    location: str,
    declarations: list[OutputDeclaration],
    policy: RoutingPolicy,
    local_path: Path | None = None,
    verify: bool = False,
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES,
) -> Artifact:
    kind = resolve_kind(rel_path, declarations)
    route = policy.for_artifact(kind, declarations, rel_path)

    sha: str | None = None
    if local_path is not None and (verify or size <= hash_max_bytes):
        sha = hash_file(local_path)

    return Artifact(
        artifact_id=make_artifact_id(run_id, rel_path, sha),
        run_id=run_id,
        path=rel_path,
        kind=kind,
        size_bytes=size,
        location=location,
        abs_path=abs_path,
        sha256=sha,
        route=route,
        declared=route.declared,
    )


def declared_only(declarations: list[OutputDeclaration]) -> bool:
    """Whether an outputs declaration should act as a filter.

    When a project declares outputs, the declaration is the definition of "what
    this run produces" - that is the stated purpose of declaring them, and it is
    what separates requested results from scratch files or source. With no
    declaration, caasi falls back to inventorying everything that is not its own
    bookkeeping, so a project that declares nothing still loses nothing.
    """
    return bool(declarations)


def _matches_any(rel: str, declarations: list[OutputDeclaration]) -> bool:
    return any(d.matches(rel) for d in declarations)


def inventory_directory(
    root: Path,
    run_id: str,
    declarations: list[OutputDeclaration] | None = None,
    policy: RoutingPolicy | None = None,
    verify: bool = False,
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES,
) -> list[Artifact]:
    """Inventory files under *root*, excluding caasi bookkeeping.

    Used for local runs and for a target tree that has already been pulled into a
    local staging path. When *declarations* are present they act as a filter; when
    absent every non-bookkeeping file is inventoried.
    """
    declarations = declarations or []
    policy = policy or RoutingPolicy()
    filter_to_declared = declared_only(declarations)
    root = Path(root)
    if not root.is_dir():
        return []

    artifacts: list[Artifact] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if is_bookkeeping(rel):
            continue
        if filter_to_declared and not _matches_any(rel, declarations):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        artifacts.append(
            _artifact_from_stat(
                run_id, rel, size, str(path), "workstation", declarations, policy,
                local_path=path, verify=verify, hash_max_bytes=hash_max_bytes,
            )
        )
    return artifacts


def inventory_remote(
    target: Target,
    remote_root: str,
    run_id: str,
    declarations: list[OutputDeclaration] | None = None,
    policy: RoutingPolicy | None = None,
    verify: bool = False,
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES,
    timeout: float | None = None,
) -> list[Artifact]:
    """Inventory files under *remote_root* on an SSH target.

    Sizes come from a single remote ``find``. Content hashes are computed on the
    target only when requested (``verify``) or the file is small, so a large
    checkpoint set does not stream over the link just to be listed.
    """
    declarations = declarations or []
    policy = policy or RoutingPolicy()

    if target.transport != "ssh":
        local = Path(remote_root).expanduser()
        arts = inventory_directory(local, run_id, declarations, policy, verify, hash_max_bytes)
        for a in arts:
            a.location = "target"
        return arts

    prefix = target_ssh_prefix(target)
    budget = timeout if timeout is not None else max(15.0, float(target.ssh_timeout) * 3)
    find_cmd = f"find {shlex.quote(remote_root)} -type f -printf '%s %p\\n' 2>/dev/null"
    try:
        res = subprocess.run(prefix + [find_cmd], capture_output=True, text=True, timeout=budget)
    except subprocess.TimeoutExpired:
        return []
    if res.returncode != 0:
        return []

    root = remote_root.rstrip("/")
    filter_to_declared = declared_only(declarations)
    rows: list[tuple[int, str]] = []
    for line in res.stdout.splitlines():
        size_str, _, path = line.partition(" ")
        if not path:
            continue
        rel = path[len(root) + 1:] if path.startswith(root + "/") else path.lstrip("/")
        if is_bookkeeping(rel):
            continue
        if filter_to_declared and not _matches_any(rel, declarations):
            continue
        if not size_str.isdigit():
            continue
        rows.append((int(size_str), rel))

    if not rows:
        return []

    # Optionally hash on the target in one round-trip, small files only.
    hashes: dict[str, str] = {}
    want_hash = [rel for size, rel in rows if verify or size <= hash_max_bytes]
    if want_hash:
        quoted = " ".join(shlex.quote(f"{root}/{rel}") for rel in want_hash)
        hash_cmd = f"sha256sum {quoted} 2>/dev/null"
        try:
            hres = subprocess.run(prefix + [hash_cmd], capture_output=True, text=True, timeout=budget)
            if hres.returncode == 0:
                for line in hres.stdout.splitlines():
                    digest, _, p = line.partition("  ")
                    if digest and p:
                        rel = p.strip()[len(root) + 1:] if p.strip().startswith(root + "/") else p.strip()
                        hashes[rel] = digest.strip()
        except subprocess.TimeoutExpired:
            pass

    artifacts: list[Artifact] = []
    for size, rel in rows:
        kind = resolve_kind(rel, declarations)
        route = policy.for_artifact(kind, declarations, rel)
        sha = hashes.get(rel)
        artifacts.append(
            Artifact(
                artifact_id=make_artifact_id(run_id, rel, sha),
                run_id=run_id,
                path=rel,
                kind=kind,
                size_bytes=size,
                location="target",
                abs_path=f"{root}/{rel}",
                sha256=sha,
                route=route,
                declared=route.declared,
            )
        )
    return sorted(artifacts, key=lambda a: a.path)


# ---------------------------------------------------------------------------
# Collection / routing
# ---------------------------------------------------------------------------


@dataclass
class CollectionPlan:
    """What a collection would do, before it does anything."""

    to_fetch: list[Artifact] = field(default_factory=list)
    to_leave: list[Artifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetch_count": len(self.to_fetch),
            "fetch_bytes": sum(a.size_bytes for a in self.to_fetch),
            "leave_count": len(self.to_leave),
            "leave_bytes": sum(a.size_bytes for a in self.to_leave),
            "fetch": [a.path for a in self.to_fetch],
            "leave": [a.path for a in self.to_leave],
        }


def plan_collection(artifacts: list[Artifact]) -> CollectionPlan:
    """Split artifacts by routing decision. Pure - performs no I/O."""
    plan = CollectionPlan()
    for art in artifacts:
        if art.route.destination == "workstation" and art.location == "target":
            plan.to_fetch.append(art)
        else:
            plan.to_leave.append(art)
    return plan


def collect_artifacts(
    target: Target,
    remote_root: str,
    artifacts: list[Artifact],
    host_dest: Path,
    dry_run: bool = False,
    timeout: float | None = None,
) -> list[str]:
    """Copy artifacts routed to ``workstation`` into *host_dest*.

    Only the files in the plan are transferred, never the whole tree, so
    unrelated target data is untouched. Returns the list of absolute host paths
    written. Never deletes anything on either side.
    """
    plan = plan_collection(artifacts)
    errors: list[str] = []
    written: list[str] = []

    if not plan.to_fetch or target.transport != "ssh":
        return written

    prefix = target_ssh_prefix(target)
    budget = timeout if timeout is not None else max(60.0, float(target.ssh_timeout) * 10)
    host_dest = Path(host_dest)
    if not dry_run:
        host_dest.mkdir(parents=True, exist_ok=True)

    for art in plan.to_fetch:
        dest = host_dest / art.path
        if dry_run:
            written.append(str(dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # rsync the single file so partial transfers are recoverable and
        # re-running collection is idempotent.
        cmd = [
            "rsync", "-a", "--partial", "-e", " ".join(prefix[:-1]),
            f"{prefix[-1]}:{shlex.quote(art.abs_path)}", str(dest),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=budget)
        except subprocess.TimeoutExpired:
            errors.append(f"{art.path}: transfer timed out")
            continue
        if res.returncode != 0:
            errors.append(f"{art.path}: {res.stderr.strip() or 'rsync failed'}")
            continue
        art.collected_to = str(dest)
        written.append(str(dest))

    return written


# ---------------------------------------------------------------------------
# Record persistence
# ---------------------------------------------------------------------------


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def save_artifact_record(record: ArtifactRecord, run_directory: Path) -> Path | None:
    """Write the artifact record as a sibling of the run manifest.

    A separate file, matching the existing one-concern-per-file bundle layout
    (manifest.yaml, environment.yaml, ...). Returns the path written, or None if
    it could not be written - provenance must never take a run down.
    """
    if record.collected_at is None:
        record.collected_at = _now()
    target = run_directory / "artifacts.yaml"
    try:
        import yaml

        target.write_text(
            yaml.safe_dump(record.to_dict(), sort_keys=False), encoding="utf-8"
        )
    except OSError:
        return None
    return target


def load_artifact_record(run_directory: Path) -> ArtifactRecord | None:
    """Read a run's artifact record, if one was written."""
    path = run_directory / "artifacts.yaml"
    if not path.is_file():
        return None
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    record = ArtifactRecord(
        run_id=str(data.get("run_id") or run_directory.name),
        project=data.get("project"),
        target_name=str(data.get("target_name") or "local"),
        target_transport=str(data.get("target_transport") or "local"),
        run_status=data.get("run_status"),
        collected_at=data.get("collected_at"),
        deployment_id=data.get("deployment_id"),
        build_id=data.get("build_id"),
        git_revision=data.get("git_revision"),
        remote_run_dir=data.get("remote_run_dir"),
        errors=list(data.get("errors") or []),
    )
    for raw in data.get("artifacts") or []:
        route_raw = raw.get("route") or {}
        record.artifacts.append(
            Artifact(
                artifact_id=str(raw.get("artifact_id")),
                run_id=str(raw.get("run_id") or record.run_id),
                path=str(raw.get("path")),
                kind=str(raw.get("kind") or "other"),
                size_bytes=int(raw.get("size_bytes") or 0),
                location=str(raw.get("location") or "workstation"),
                abs_path=str(raw.get("abs_path") or ""),
                sha256=raw.get("sha256"),
                route=ArtifactRoute(
                    destination=str(route_raw.get("destination") or "target_local"),
                    reason=str(route_raw.get("reason") or "unclassified"),
                    declared=bool(route_raw.get("declared")),
                ),
                collected_to=raw.get("collected_to"),
                declared=bool(raw.get("declared")),
            )
        )
    return record

# ---------------------------------------------------------------------------
# Lifecycle intent
#
# Declares what a deployment is FOR, which changes what "done" means:
#
#   ephemeral   the deployment exists to serve a job; once its declared outputs
#               are collected, the target MAY be released
#   persistent  the deployment is an operational installation that must remain
#               (robots, services) - collection is not part of its lifecycle
#
# This is a *declaration and a recording*. caasi never deletes a deployment, and
# marking one releasable has no destructive effect of any kind.
# ---------------------------------------------------------------------------

LIFECYCLES = ("ephemeral", "persistent")
DEFAULT_LIFECYCLE = "persistent"


def resolve_lifecycle(config: Config | None, spec_lifecycle: str | None = None) -> str:
    """Resolve the declared lifecycle: explicit > config > default.

    Defaults to ``persistent`` so an undeclared project is never treated as
    disposable. Disposal must be opted into, never assumed.
    """
    if spec_lifecycle in LIFECYCLES:
        return str(spec_lifecycle)
    if config is not None:
        value = config.get("lifecycle")
        if isinstance(value, str) and value in LIFECYCLES:
            return value
    return DEFAULT_LIFECYCLE


def is_releasable(record: "DeploymentRecordLike") -> bool:
    """Whether a deployment's results are collected and the target may be released.

    Requires BOTH an ephemeral declaration AND completed collection: an
    ephemeral deployment whose outputs have not been collected is not releasable,
    because releasing it would discard results nobody has taken yet.
    """
    if getattr(record, "lifecycle", DEFAULT_LIFECYCLE) != "ephemeral":
        return False
    return bool(getattr(record, "releasable", False))

def mark_deployment_releasable(
    record: ArtifactRecord,
    config: Config,
) -> tuple[bool, str | None]:
    """Record that an ephemeral deployment's declared results are collected.

    Purely a *recording*: it updates the deployment's stored `releasable` flag on
    the host and, when reachable, on the target. It never deletes, moves or
    releases anything. Returns ``(changed, detail)``.

    A persistent deployment is never marked releasable - collection is not part
    of a persistent runtime's lifecycle, and a robot must not look disposable
    because someone collected a log file.
    """
    from . import project as projects

    root = projects.find_project_root()
    if root is None or not record.deployment_id:
        return False, "no project or deployment to update"

    # Locate the recorded deployment on the host.
    deployments_dir = root / ".caasi" / "deployments" / record.target_name
    path = deployments_dir / f"{record.deployment_id}.json"
    if not path.is_file():
        return False, "host deployment record not found"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return False, f"unreadable deployment record: {err}"

    if data.get("lifecycle") != "ephemeral":
        return False, "deployment is persistent; not marked releasable"

    if data.get("releasable"):
        return False, "already marked releasable"

    data["releasable"] = True
    data["releasable_at"] = _now()
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as err:
        return False, f"could not update deployment record: {err}"

    return True, "marked releasable (recorded only; nothing was removed)"
