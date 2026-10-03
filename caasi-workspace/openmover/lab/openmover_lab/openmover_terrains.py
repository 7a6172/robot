"""Procedural obstacle terrains for the openmover navigation task.

Source-world generator for the NMTE transfer study: each env gets its own
tile — a flat room enclosed by boundary walls with random interior walls.
Difficulty scales the number of interior walls, so a single generator config
spawns a distribution of maze-like worlds (train here, transfer elsewhere).

Design notes:
- Walls are taller than the LiDAR height (~0.13 m) so every scan becomes
  informative (hits instead of all-max-range).
- The center platform (radius ``platform_radius``) is kept obstacle-free so
  the spawn point is always on flat ground.
- Boundary walls keep each robot inside its own tile over a full episode.

run6 — reconstructable layouts (blocked-goal sampling):
- The navigation env rejection-samples goals whose straight spawn->goal
  chord crosses an obstacle (run5's ring sampling rarely blocked the chord,
  so the policy learned turn-and-drive and barely any avoidance). For that
  it must know the exact obstacle layout of every tile, but Isaac's
  TerrainImporter keeps only the merged mesh and the terrain cache prevents
  generator functions from re-running. So:
  - per-tile difficulty is drawn by Isaac from a seeded Generator in a fixed
    order — the env replays that exact sequence;
  - each layout below is drawn from a per-tile RNG keyed by (seed,
    difficulty) only (_tile_rng), never from global np.random state;
  hence the env reconstructs every layout bit-exactly, cache hot or cold.
- On a cache MISS the terrain functions also register their layout in
  TERRAIN_LAYOUT_REGISTRY keyed by the exact difficulty; the env asserts its
  replay against it (silent on warm-cache loads).
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from isaaclab.terrains import SubTerrainBaseCfg, TerrainGeneratorCfg
from isaaclab.terrains.trimesh.utils import make_plane
from isaaclab.utils.configclass import configclass


# On a cache MISS the terrain functions register their layout here, keyed by
# the exact difficulty Isaac passed; the env uses it to assert that its
# difficulty replay reproduces the physical terrain (see module docstring).
TERRAIN_LAYOUT_REGISTRY: dict[float, list[tuple[float, float, float, float, float, float]]] = {}


def _tile_rng(seed: int | None, difficulty: float) -> np.random.RandomState:
    """Deterministic per-tile RNG keyed ONLY by (seed, difficulty).

    Layout functions must never touch global np.random: its state depends on
    the whole process history and cannot be reconstructed by the env.
    """
    bits = int(np.array(difficulty, dtype=np.float64).view(np.uint64).item())
    key = (bits ^ (int(seed or 0) * 0x9E3779B9)) & 0xFFFFFFFF
    return np.random.RandomState(key)


def _wall_maze_layout(difficulty: float, cfg: "WallMazeTerrainCfg", rng: np.random.RandomState):
    """All wall boxes (incl. boundary) as (cx, cy, yaw, length, width, height).

    Coordinates are tile-local with the tile corner at (0, 0) — the frame the
    meshes are built in. SINGLE SOURCE OF TRUTH: the terrain function builds
    meshes from this; the env reconstructs it for blocked-goal sampling.
    """
    size_x, size_y = cfg.size
    t, bh = cfg.wall_thickness, cfg.boundary_height
    # boundary walls (inside the tile edges)
    boxes = [
        (0.5 * size_x, 0.5 * t, 0.0, size_x, t, bh),
        (0.5 * size_x, size_y - 0.5 * t, 0.0, size_x, t, bh),
        (0.5 * t, 0.5 * size_y, 0.0, t, size_y, bh),
        (size_x - 0.5 * t, 0.5 * size_y, 0.0, t, size_y, bh),
    ]
    # interior walls, difficulty controls count; keep spawn platform clear
    num_walls = int(cfg.num_walls_range[0] + difficulty * (cfg.num_walls_range[1] - cfg.num_walls_range[0]))
    margin = 0.5 * t + 0.15
    placed, attempts = 0, 0
    while placed < num_walls and attempts < 50 * num_walls:
        attempts += 1
        length = rng.uniform(*cfg.wall_length_range)
        cx = rng.uniform(margin, size_x - margin)
        cy = rng.uniform(margin, size_y - margin)
        # conservative clearance: wall center must sit outside platform + half length
        if np.hypot(cx - 0.5 * size_x, cy - 0.5 * size_y) < cfg.platform_radius + 0.5 * length + 0.2:
            continue
        height = rng.uniform(*cfg.wall_height_range)
        yaw = rng.uniform(0.0, np.pi)
        boxes.append((cx, cy, yaw, length, t, height))
        placed += 1
    return boxes


def wall_maze_terrain(difficulty: float, cfg: "WallMazeTerrainCfg") -> tuple[list[trimesh.Trimesh], np.ndarray]:
    """Flat room with boundary walls and random interior walls.

    Args:
        difficulty: Scales the number of interior walls between ``num_walls_range``.
        cfg: Terrain configuration.

    Returns:
        Tuple of (list of trimesh meshes, terrain origin). The mesh occupies
        [0, size[0]] x [0, size[1]] with the origin at its center.
    """
    rng = _tile_rng(cfg.seed, difficulty)
    boxes = _wall_maze_layout(difficulty, cfg, rng)
    TERRAIN_LAYOUT_REGISTRY[difficulty] = boxes

    size_x, size_y = cfg.size
    meshes = [make_plane(cfg.size, height=0.0, center_zero=False)]
    origin = np.array([0.5 * size_x, 0.5 * size_y, 0.0])
    for cx, cy, yaw, length, width, height in boxes:
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_euler("z", yaw).as_matrix()
        transform[:3, 3] = (cx, cy, 0.5 * height)
        meshes.append(trimesh.creation.box(extents=(length, width, height), transform=transform))

    return meshes, origin


@configclass
class WallMazeTerrainCfg(SubTerrainBaseCfg):
    """Configuration for :func:`wall_maze_terrain`."""

    function = wall_maze_terrain
    num_walls_range: tuple[int, int] = (4, 12)
    wall_length_range: tuple[float, float] = (0.8, 2.0)
    wall_height_range: tuple[float, float] = (0.4, 0.7)
    wall_thickness: float = 0.1
    boundary_height: float = 0.5
    platform_radius: float = 1.0
    # cache-buster: the terrain cache key hashes every cfg field, so bump this
    # whenever the layout logic changes (run6: deterministic per-tile RNG)
    layout_version: int = 2


OPENMOVER_TERRAINS_CFG = TerrainGeneratorCfg(
    size=(8.0, 8.0),
    num_rows=32,
    num_cols=32,
    curriculum=False,
    use_cache=True,
    seed=42,  # required for reproducible cached terrain generation
    sub_terrains={
        "wall_maze": WallMazeTerrainCfg(proportion=1.0),
    },
)


# --------------------------------------------------------------------- rail yard
# Target 1/3 geometry per docs/research/06_validation_plan.md: flat-floor
# maintenance yard/depot (NOT ballast). Tracks rendered as floor-level
# obstacles with a level-crossing gap so both tile halves stay reachable.


def _rotated_box(length: float, width: float, height: float, cx: float, cy: float, yaw: float) -> trimesh.Trimesh:
    transform = np.eye(4)
    transform[:3, :3] = Rotation.from_euler("z", yaw).as_matrix()
    transform[:3, 3] = (cx, cy, 0.5 * height)
    return trimesh.creation.box(extents=(length, width, height), transform=transform)


def _rail_yard_layout(difficulty: float, cfg: "RailYardTerrainCfg", rng: np.random.RandomState):
    """All obstacle boxes as (cx, cy, yaw, length, width, height).

    Fence + rails + clutter in tile-corner coordinates. SINGLE SOURCE OF
    TRUTH, see :func:`_wall_maze_layout`. Rails are included so the
    blocked-goal sampling forces level-crossing routes across the track band.
    """
    size_x, size_y = cfg.size
    t, bh = cfg.wall_thickness, cfg.boundary_height
    # boundary fence
    boxes = [
        (0.5 * size_x, 0.5 * t, 0.0, size_x, t, bh),
        (0.5 * size_x, size_y - 0.5 * t, 0.0, size_x, t, bh),
        (0.5 * t, 0.5 * size_y, 0.0, t, size_y, bh),
        (size_x - 0.5 * t, 0.5 * size_y, 0.0, t, size_y, bh),
    ]

    # track band: two rails along x with one level-crossing gap
    y_track = rng.uniform(cfg.track_y_range[0], cfg.track_y_range[1]) * size_y
    gap_width = rng.uniform(*cfg.crossing_width_range)
    gap_x = rng.uniform(0.25 * size_x, 0.75 * size_x)
    rail_w, rail_h = cfg.rail_width, cfg.rail_height
    half_gauge = 0.5 * cfg.gauge
    for dy in (-half_gauge, half_gauge):
        west_len = (gap_x - 0.5 * gap_width) - t
        east_len = (size_x - t) - (gap_x + 0.5 * gap_width)
        if west_len > 0.1:
            boxes.append((t + 0.5 * west_len, y_track + dy, 0.0, west_len, rail_w, rail_h))
        if east_len > 0.1:
            boxes.append((gap_x + 0.5 * gap_width + 0.5 * east_len, y_track + dy, 0.0, east_len, rail_w, rail_h))
    band_lo = y_track - half_gauge - 0.4
    band_hi = y_track + half_gauge + 0.4

    # clutter (ducts, tool carts, service vehicles), spawn platform kept clear
    items: list[tuple[float, float]] = []  # (length, width) of each item to place
    items += [cfg.duct_size] * int(
        cfg.num_ducts_range[0] + difficulty * (cfg.num_ducts_range[1] - cfg.num_ducts_range[0])
    )
    items += [cfg.cart_size] * int(
        cfg.num_carts_range[0] + difficulty * (cfg.num_carts_range[1] - cfg.num_carts_range[0])
    )
    if rng.uniform() < cfg.vehicle_probability:
        items.append(cfg.vehicle_size)

    margin = 0.5 * t + 0.15
    for length, width in items:
        placed, attempts = False, 0
        half_diag = 0.5 * np.hypot(length, width)
        while not placed and attempts < 100:
            attempts += 1
            cx = rng.uniform(margin, size_x - margin)
            cy = rng.uniform(margin, size_y - margin)
            if np.hypot(cx - 0.5 * size_x, cy - 0.5 * size_y) < cfg.platform_radius + half_diag + 0.2:
                continue  # keep the spawn platform clear
            if band_lo < cy < band_hi:
                continue  # keep the track band clear
            yaw = rng.uniform(0.0, np.pi)
            boxes.append((cx, cy, yaw, length, width, cfg.clutter_height))
            placed = True

    return boxes


def rail_yard_terrain(difficulty: float, cfg: "RailYardTerrainCfg") -> tuple[list[trimesh.Trimesh], np.ndarray]:
    """Flat depot floor with a track band, ducts, tool carts and vehicles.

    Args:
        difficulty: Scales the clutter count.
        cfg: Terrain configuration.

    Returns:
        Tuple of (list of trimesh meshes, terrain origin).
    """
    rng = _tile_rng(cfg.seed, difficulty)
    boxes = _rail_yard_layout(difficulty, cfg, rng)
    TERRAIN_LAYOUT_REGISTRY[difficulty] = boxes

    size_x, size_y = cfg.size
    meshes = [make_plane(cfg.size, height=0.0, center_zero=False)]
    origin = np.array([0.5 * size_x, 0.5 * size_y, 0.0])
    for cx, cy, yaw, length, width, height in boxes:
        meshes.append(_rotated_box(length, width, height, cx, cy, yaw))

    return meshes, origin


@configclass
class RailYardTerrainCfg(SubTerrainBaseCfg):
    """Configuration for :func:`rail_yard_terrain` (Target 1/3 geometry)."""

    function = rail_yard_terrain
    wall_thickness: float = 0.1
    boundary_height: float = 0.5
    platform_radius: float = 1.0
    # track: standard gauge, stylized as floor-level obstacles tall enough for the LiDAR
    gauge: float = 1.435
    rail_width: float = 0.08
    rail_height: float = 0.25
    track_y_range: tuple[float, float] = (0.65, 0.82)  # fraction of tile size, away from center
    crossing_width_range: tuple[float, float] = (1.0, 1.5)
    # clutter
    duct_size: tuple[float, float] = (1.6, 0.3)
    cart_size: tuple[float, float] = (0.7, 0.5)
    vehicle_size: tuple[float, float] = (2.2, 1.2)
    clutter_height: float = 0.6
    num_ducts_range: tuple[int, int] = (1, 2)
    num_carts_range: tuple[int, int] = (1, 4)
    vehicle_probability: float = 0.6
    # cache-buster: bump when the layout logic changes (see WallMazeTerrainCfg)
    layout_version: int = 2


RAIL_YARD_TERRAINS_CFG = TerrainGeneratorCfg(
    size=(8.0, 8.0),
    num_rows=32,
    num_cols=32,
    curriculum=False,
    use_cache=True,
    seed=43,
    sub_terrains={
        "rail_yard": RailYardTerrainCfg(proportion=1.0),
    },
)

# terrain function -> layout function; the env uses this to reconstruct the
# obstacle footprints of every tile for blocked-goal sampling
TERRAIN_LAYOUT_FNS = {
    wall_maze_terrain: _wall_maze_layout,
    rail_yard_terrain: _rail_yard_layout,
}


# ---------------------------------------------------------------- custom maps
# Gallery / user-authored worlds ("draw a map, say go"): a JSON spec holding
# wall boxes + spawn + goal in tile-local coordinates, produced by
# 27_make_custom_map.py (from a PNG drawing or a programmatic generator).

_CUSTOM_MAP_CACHE: dict[str, dict] = {}


def load_custom_map(path: str) -> dict:
    """Load (and cache) a custom-map JSON spec.

    Required keys: ``size`` [x, y] m, ``boxes`` [[cx, cy, yaw, length, width,
    height], ...] tile-local (corner origin), ``spawn`` [x, y], ``goal``
    [x, y] (tile-local).
    """
    import json
    from pathlib import Path

    key = str(Path(path).resolve())
    if key not in _CUSTOM_MAP_CACHE:
        with open(key) as f:
            spec = json.load(f)
        for k in ("size", "boxes", "spawn", "goal"):
            if k not in spec:
                raise ValueError(f"custom map {key} missing required key '{k}'")
        _CUSTOM_MAP_CACHE[key] = spec
    return _CUSTOM_MAP_CACHE[key]


def _custom_map_layout(difficulty: float, cfg: "CustomMapTerrainCfg", rng: np.random.RandomState):
    """Boxes of the map file — difficulty-independent, identical on every tile."""
    return [tuple(b) for b in load_custom_map(cfg.map_file)["boxes"]]


def custom_map_terrain(difficulty: float, cfg: "CustomMapTerrainCfg") -> tuple[list[trimesh.Trimesh], np.ndarray]:
    """Terrain built from a user-authored map file (see :func:`load_custom_map`).

    Args:
        difficulty: Ignored (the map file fully defines the layout).
        cfg: Terrain configuration carrying the map path.

    Returns:
        Tuple of (list of trimesh meshes, terrain origin).
    """
    if not cfg.map_file:
        raise ValueError("CustomMapTerrainCfg.map_file is empty — pass --map_file to the runner")
    boxes = _custom_map_layout(difficulty, cfg, None)
    TERRAIN_LAYOUT_REGISTRY[difficulty] = boxes

    size_x, size_y = cfg.size
    meshes = [make_plane(cfg.size, height=0.0, center_zero=False)]
    origin = np.array([0.5 * size_x, 0.5 * size_y, 0.0])
    for cx, cy, yaw, length, width, height in boxes:
        meshes.append(_rotated_box(length, width, height, cx, cy, yaw))

    return meshes, origin


@configclass
class CustomMapTerrainCfg(SubTerrainBaseCfg):
    """Configuration for :func:`custom_map_terrain`."""

    function = custom_map_terrain
    map_file: str = ""
    # md5 of the map file CONTENT: Isaac keys the terrain cache on the hash of
    # this cfg dict, so editing the map in place (same path) would otherwise
    # silently reload the stale cached mesh (robot spawned inside old walls).
    map_hash: str = ""
    # cache-buster: bump when the spec format or mesh construction changes
    # (2: tile size now taken from the map spec instead of hardcoded 8x8)
    layout_version: int = 2


def custom_map_terrains_cfg(map_file: str, num_tiles: int = 4) -> TerrainGeneratorCfg:
    """Small generator stamping one authored map onto every tile.

    Tiles are sized so each env can get its own (the env assigns round-robin
    and REJECTS num_envs > tiles: a shared tile would stack robots on the
    fixed map spawn). num_tiles=4 (2x2) reproduces the original single-env
    eval setting; campaign runs pass num_envs so seeds fold in parallel.
    use_cache=True + map_hash: all tiles share ONE cached mesh, so extra
    tiles cost origins, not geometry.
    """
    import hashlib
    import math
    from pathlib import Path

    content = Path(map_file).read_bytes()
    spec = load_custom_map(map_file)
    side = max(2, math.ceil(math.sqrt(max(int(num_tiles), 4))))
    return TerrainGeneratorCfg(
        # the tile MUST match the map canvas: the terrain origin is the tile
        # centre and every env-side conversion (spawn/goal corner->centre,
        # obstacle table, geodesic grid) reads this size. The old hardcoded
        # (8, 8) built 10 m maps on 8 m tiles -- a 1 m frame offset between
        # the robot/goal frame and the walls.
        size=(float(spec["size"][0]), float(spec["size"][1])),
        num_rows=side,
        num_cols=side,
        curriculum=False,
        use_cache=True,
        seed=44,
        sub_terrains={
            "custom_map": CustomMapTerrainCfg(
                proportion=1.0, map_file=map_file,
                map_hash=hashlib.md5(content).hexdigest(),
            ),
        },
    )


TERRAIN_LAYOUT_FNS[custom_map_terrain] = _custom_map_layout
