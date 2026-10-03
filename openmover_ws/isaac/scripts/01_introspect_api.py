"""API introspection: dump signatures of the functions the bring-up scripts need."""

from common import preflight

preflight("introspect")

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})

import importlib  # noqa: E402
import inspect  # noqa: E402

print("=== isaacsim.core.prims members", flush=True)
import isaacsim.core.prims as prims_mod  # noqa: E402
print([n for n in dir(prims_mod) if not n.startswith("_")], flush=True)

from isaacsim.core.prims import Articulation  # noqa: E402
print("=== prims.Articulation methods (subset)", flush=True)
for name in ("apply_action", "initialize", "set_gains", "get_joint_names",
             "set_world_pose", "get_world_pose", "get_joint_positions",
             "set_joint_positions", "write_root_state_to_sim",
             "reset", "find_joints"):
    fn = getattr(Articulation, name, None)
    if fn is None:
        print(f"  {name} ABSENT", flush=True)
        continue
    try:
        print(f"  {name}{inspect.signature(fn)}", flush=True)
    except (ValueError, TypeError):
        print(f"  {name} (no sig)", flush=True)

print("=== ArticulationAction", flush=True)
try:
    from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
    print(f"  {inspect.signature(ArticulationAction.__init__)}", flush=True)
except Exception as e:  # noqa: BLE001
    print("  utils.types:", e, flush=True)
    try:
        from isaacsim.core.prims import ArticulationAction  # noqa: E402
        print(f"  from prims: {inspect.signature(ArticulationAction.__init__)}",
              flush=True)
    except Exception as e2:  # noqa: BLE001
        print("  prims too:", e2, flush=True)

simulation_app.close()
print("[introspect] done", flush=True)
