import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Keep this focused plugin test independent of COVAS audio/database imports.
# Production imports these real modules; here only the type name and planner
# call boundary are needed.
helper_stub = ModuleType("lib.PluginHelper")
helper_stub.PluginHelper = type("PluginHelper", (), {})
sys.modules["lib.PluginHelper"] = helper_stub

planner_stub = ModuleType("lib.actions.ExobiologyPlanner")
planner_stub.plan_exobiology = lambda _args, _context: {}
sys.modules["lib.actions.ExobiologyPlanner"] = planner_stub

PLUGIN_PATH = ROOT / "plugins" / "exobiology-profit-planner" / "plugin.py"
SPEC = importlib.util.spec_from_file_location("exobiology_profit_planner_plugin", PLUGIN_PATH)
assert SPEC and SPEC.loader
plugin_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin_module)


def clustered_plan() -> dict:
    return {
        "strategy": "stratum_sniping",
        "source_system": "Start",
        "source_coords": {"x": 3000.0, "y": 0.0, "z": 0.0},
        "jump_range": 60.0,
        "radius_ly": 500,
        "max_arrival_ls": 1700,
        "outward_staging_applied": False,
        "targets": [
            {
                "system": "Cluster",
                "distance_ly": 40.0,
                "distance_from_sol_ly": 3040.0,
                "estimated_jumps": 1,
                "route_order": 1,
                "confidence_tier": "high",
                "confidence": "better lead, still not a guarantee",
                "bodies": [
                    {
                        "body": "Cluster A 2",
                        "distance_to_arrival_ls": 200.0,
                        "atmosphere": "Thin Carbon dioxide",
                        "gravity_g": 0.3,
                        "surface_temperature_k": 220.0,
                        "updated_at": "2020-01-01",
                    },
                    {
                        "body": "Cluster A 3",
                        "distance_to_arrival_ls": 700.0,
                        "atmosphere": "Thin Sulphur dioxide",
                        "gravity_g": 0.4,
                        "surface_temperature_k": 250.0,
                        "updated_at": "2019-01-01",
                    },
                ],
            },
            {
                "system": "Singleton",
                "distance_ly": 55.0,
                "distance_from_sol_ly": 3055.0,
                "estimated_jumps": 2,
                "route_order": 2,
                "confidence_tier": "high",
                "confidence": "better lead, still not a guarantee",
                "bodies": [{"body": "Singleton 4", "distance_to_arrival_ls": 350.0}],
            },
        ],
    }


def make_plugin(tmp_path: Path):
    manifest = plugin_module.PluginManifest(json.dumps({
        "guid": "test-guid",
        "name": "Test",
        "version": "2.0.0",
        "entrypoint": "plugin.py",
    }))
    plugin = plugin_module.ExobiologyProfitPlannerPlugin(manifest)
    plugin._expedition_file = tmp_path / "expedition.json"
    plotted: list[dict] = []

    def plot(args, _context):
        plotted.append(args)
        return "plotted"

    plugin._helper = SimpleNamespace(
        _action_manager=SimpleNamespace(actions={"plotToTarget": {"method": plot}})
    )
    return plugin, plotted


def test_find_action_delegates_all_strategies_and_arrival_cap_to_core(monkeypatch) -> None:
    captured = []

    def fake_plan(args, context):
        captured.append((args, context))
        return {"strategy": "stratum_sniping", "targets": [], "navigation_instruction": None}

    monkeypatch.setattr(plugin_module, "plan_exobiology", fake_plan)
    parameters = plugin_module.PlannerParameters(
        strategy="first_discovery",
        radius=450,
        max_results=7,
        max_arrival_ls=1200,
    )
    context = {"Location": {"StarSystem": "Start"}}
    result = json.loads(plugin_module._plan(parameters, context))

    assert captured == [({
        "strategy": "first_discovery",
        "radius": 450,
        "max_results": 7,
        "max_arrival_ls": 1200,
    }, context)]
    assert result["strategy"] == "stratum_sniping"
    assert "Never run a full-system FSS" in result["next_action"]


def test_expedition_queue_preserves_every_exact_body_in_cluster() -> None:
    queue = plugin_module._expedition_queue(clustered_plan())

    assert [(item["system"], item["body"]) for item in queue] == [
        ("Cluster", "Cluster A 2"),
        ("Cluster", "Cluster A 3"),
        ("Singleton", "Singleton 4"),
    ]
    assert queue[0]["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert queue[1]["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert "do not scan the rest of the system" in queue[0]["instruction"]


def test_planning_persists_body_queue_and_plots_system_first(tmp_path, monkeypatch) -> None:
    plugin, plotted = make_plugin(tmp_path)
    captured = []

    def fake_plan(args, context):
        captured.append((args, context))
        return clustered_plan()

    monkeypatch.setattr(plugin_module, "plan_exobiology", fake_plan)
    parameters = plugin_module.TectonicasExpeditionParameters(
        max_systems=4,
        search_radius_ly=450,
        max_arrival_ls=1300,
    )
    context = {"Location": {"StarSystem": "Start"}}
    result = json.loads(plugin._plan_tectonicas_expedition(parameters, context))
    persisted = json.loads(plugin._expedition_file.read_text(encoding="utf-8"))

    assert captured[0][0] == {
        "strategy": "stratum_sniping",
        "radius": 450,
        "max_results": 4,
        "max_arrival_ls": 1300,
    }
    assert [(item["system"], item["body"]) for item in persisted["targets"]] == [
        ("Cluster", "Cluster A 2"),
        ("Cluster", "Cluster A 3"),
        ("Singleton", "Singleton 4"),
    ]
    assert plotted == [{"system": "Cluster"}]
    assert result["body_queue_size"] == 3
    assert result["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert "First Footfall is a surface marker and pays no bonus" in result["warning"]


def test_next_and_previous_select_exact_body_only_inside_target_system(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 2, "strategy": "stratum_sniping", "index": 0, "targets": queue})
    context = {"Location": {"StarSystem": "Cluster"}}

    next_result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="next"), context
    ))
    previous_result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="previous"), context
    ))

    assert plotted == [
        {"system": "Cluster", "body": "Cluster A 3"},
        {"system": "Cluster", "body": "Cluster A 2"},
    ]
    assert next_result["current_target"]["body"] == "Cluster A 3"
    assert next_result["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert previous_result["current_target"]["body"] == "Cluster A 2"


def test_next_to_another_system_plots_system_not_remote_body(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 2, "strategy": "stratum_sniping", "index": 1, "targets": queue})

    result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="next"),
        {"Location": {"StarSystem": "Cluster"}},
    ))

    assert plotted == [{"system": "Singleton"}]
    assert result["current_target"]["body"] == "Singleton 4"
    assert result["plot_result"]["requested"] == {"system": "Singleton"}
