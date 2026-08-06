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

    def plot(args, context):
        plotted.append(args)
        if args.get("body"):
            return f"In-system navigation to {args['body']} completed."
        context.setdefault("NavInfo", {})["NavRoute"] = [{"StarSystem": args["system"]}]
        return f"Route to {args['system']} successfully plotted (Jumps: 3)"

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


def test_expedition_queue_groups_every_exact_body_by_system() -> None:
    queue = plugin_module._expedition_queue(clustered_plan())

    assert [item["system"] for item in queue] == ["Cluster", "Singleton"]
    assert queue[0]["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert queue[0]["candidate_count"] == 2
    assert queue[1]["targeted_fss_bodies"] == ["Singleton 4"]
    assert "operation next" in queue[0]["instruction"]


def test_planning_persists_system_queue_and_plots_system_first(tmp_path, monkeypatch) -> None:
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
    assert persisted["version"] == 3
    assert persisted["queue_granularity"] == "system"
    assert [item["system"] for item in persisted["targets"]] == ["Cluster", "Singleton"]
    assert plotted == [{"system": "Cluster"}]
    assert result["system_queue_size"] == 2
    assert result["success"] is True
    assert result["route_verified"] is True
    assert result["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]
    assert "First Footfall is a surface marker and pays no bonus" in result["warning"]


def test_next_and_previous_move_exactly_one_system(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})
    context = {"Location": {"StarSystem": "Cluster"}}

    next_result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="next"), context
    ))
    previous_result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="previous"), context
    ))

    assert plotted == [
        {"system": "Singleton"},
        {"system": "Cluster"},
    ]
    assert next_result["current_target"]["system"] == "Singleton"
    assert next_result["success"] is True
    assert next_result["route_verified"] is True
    assert next_result["targeted_fss_bodies"] == ["Singleton 4"]
    assert previous_result["current_target"]["system"] == "Cluster"


def test_next_to_another_system_plots_system_not_remote_body(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})

    result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="next"),
        {"Location": {"StarSystem": "Cluster"}},
    ))

    assert plotted == [{"system": "Singleton"}]
    assert result["current_target"]["system"] == "Singleton"
    assert result["plot_result"]["requested"] == {"system": "Singleton"}
    assert result["plot_result"]["status"] == "route_plotted"


def test_set_uses_one_based_index_and_can_skip_plot(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})

    result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set", index=2, plot=False),
        {"Location": {"StarSystem": "Cluster"}},
    ))
    persisted = plugin._load_expedition()

    assert result["success"] is True
    assert result["queue_updated"] is True
    assert result["queue_index"] == 2
    assert result["queue_progress"] == "2/2"
    assert result["current_target"]["system"] == "Singleton"
    assert result["plot_requested"] is False
    assert result["route_verified"] is False
    assert result["navigation_state"] == "no_verified_route"
    assert result["plot_result"] is None
    assert persisted["index"] == 1
    assert plotted == []


def test_set_rejects_missing_or_out_of_bounds_index_without_mutating_queue(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 1, "targets": queue})

    missing = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set"),
        {"Location": {"StarSystem": "Cluster"}},
    ))
    out_of_bounds = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set", index=3),
        {"Location": {"StarSystem": "Cluster"}},
    ))

    assert missing["success"] is False
    assert missing["valid_index_range"] == {"min": 1, "max": 2}
    assert out_of_bounds["success"] is False
    assert out_of_bounds["requested_index"] == 3
    assert out_of_bounds["valid_index_range"] == {"min": 1, "max": 2}
    assert plugin._load_expedition()["index"] == 1
    assert plotted == []


def test_set_with_plot_reports_verified_result(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})

    result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set", index=2),
        {"Location": {"StarSystem": "Cluster"}},
    ))

    assert result["success"] is True
    assert result["queue_index"] == 2
    assert result["route_verified"] is True
    assert result["navigation_verified"] is True
    assert result["navigation_state"] == "verified_route_to_target"
    assert result["plot_result"]["status"] == "route_plotted"
    assert plotted == [{"system": "Singleton"}]


def test_failed_plot_is_not_reported_as_success_but_queue_position_is_saved(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})

    def failed_plot(args, _context):
        plotted.append(args)
        return f"Failed to plot a route to {args['system']}"

    plugin._helper._action_manager.actions["plotToTarget"]["method"] = failed_plot
    result = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set", index=2),
        {"Location": {"StarSystem": "Cluster"}},
    ))

    assert result["success"] is False
    assert result["queue_updated"] is True
    assert result["queue_index"] == 2
    assert result["route_verified"] is False
    assert result["plot_result"]["status"] == "plot_failed"
    assert plugin._load_expedition()["index"] == 1


def test_body_lookup_without_selection_is_not_navigation_success() -> None:
    target = {"system": "Cluster", "body": "Cluster A 2"}
    result = plugin_module._plot_result_payload(
        "Best location found: {}. Cluster A 2 is in the current system already.",
        {"system": "Cluster", "body": "Cluster A 2"},
        target,
        {"Location": {"StarSystem": "Cluster"}},
    )

    assert result["success"] is False
    assert result["verified"] is True
    assert result["route_verified"] is False
    assert result["navigation_verified"] is True
    assert result["status"] == "body_resolved_not_selected"


def test_status_and_queue_only_set_surface_live_route_mismatch(tmp_path) -> None:
    plugin, plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 0, "targets": queue})
    context = {
        "Location": {"StarSystem": "Start"},
        "NavInfo": {
            "NextJumpTarget": "Wrong Hop",
            "NavRoute": [{"StarSystem": "Wrong Hop"}, {"StarSystem": "Wrong Destination"}],
        },
    }

    status = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="status"), context
    ))
    selected = json.loads(plugin._control_expedition(
        plugin_module.ExpeditionControlParameters(operation="set", index=2, plot=False), context
    ))

    assert status["plot_requested"] is False
    assert status["route_verified"] is False
    assert status["navigation_state"] == "route_target_mismatch"
    assert status["route_destination"] == "Wrong Destination"
    assert selected["route_verified"] is False
    assert selected["navigation_state"] == "route_target_mismatch"
    assert selected["route_destination"] == "Wrong Destination"
    assert plotted == []


def test_status_context_separates_queue_target_route_hops_and_planning_distance(tmp_path) -> None:
    plugin, _plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({
        "version": 3,
        "queue_granularity": "system",
        "strategy": "stratum_sniping",
        "source_system": "Start",
        "index": 1,
        "targets": queue,
    })

    title, status = plugin._expedition_status({
        "Location": {"StarSystem": "Cluster"},
        "NavInfo": {
            "NextJumpTarget": "Transit",
            "NavRoute": [
                {"StarSystem": "Transit"},
                {"StarSystem": "Singleton"},
            ],
        },
    })[0]

    assert title == "Active exobiology expedition"
    assert status["queue_index"] == 2
    assert status["queue_progress"] == "2/2"
    assert status["planning_source_system"] == "Start"
    assert status["target_system"] == "Singleton"
    assert status["targeted_fss_bodies"] == ["Singleton 4"]
    assert status["distance_from_planning_source_ly"] == 55.0
    assert status["navigation_state"] == "verified_route_to_target"
    assert status["route_next_hop"] == "Transit"
    assert status["route_destination"] == "Singleton"
    assert status["remaining_jumps"] == 2
    assert status["next_jump_target"] == "Transit"
    assert "one-based system index" in status["control"]


def test_status_context_calls_out_route_target_mismatch(tmp_path) -> None:
    plugin, _plotted = make_plugin(tmp_path)
    queue = plugin_module._expedition_queue(clustered_plan())
    plugin._save_expedition({"version": 3, "queue_granularity": "system", "strategy": "stratum_sniping", "index": 1, "targets": queue})

    _title, status = plugin._expedition_status({
        "Location": {"StarSystem": "Cluster"},
        "NavInfo": {
            "NextJumpTarget": "Wrong Hop",
            "NavRoute": [{"StarSystem": "Wrong Hop"}, {"StarSystem": "Wrong Destination"}],
        },
    })[0]

    assert status["target_system"] == "Singleton"
    assert status["route_destination"] == "Wrong Destination"
    assert status["navigation_state"] == "route_target_mismatch"


def test_legacy_body_queue_migrates_to_active_system_without_losing_candidates(tmp_path) -> None:
    plugin, _plotted = make_plugin(tmp_path)
    legacy_targets = [
        {
            "system": "Cluster",
            "body": "Cluster A 2",
            "targeted_fss_bodies": ["Cluster A 2", "Cluster A 3"],
            "distance_to_arrival_ls": 200.0,
        },
        {
            "system": "Cluster",
            "body": "Cluster A 3",
            "targeted_fss_bodies": ["Cluster A 2", "Cluster A 3"],
            "distance_to_arrival_ls": 700.0,
        },
        {
            "system": "Singleton",
            "body": "Singleton 4",
            "targeted_fss_bodies": ["Singleton 4"],
        },
    ]
    plugin._save_expedition({
        "version": 2,
        "strategy": "stratum_sniping",
        "index": 1,
        "targets": legacy_targets,
    })

    migrated = plugin._load_expedition()

    assert migrated["version"] == 3
    assert migrated["queue_granularity"] == "system"
    assert migrated["index"] == 0
    assert [target["system"] for target in migrated["targets"]] == ["Cluster", "Singleton"]
    assert migrated["targets"][0]["targeted_fss_bodies"] == ["Cluster A 2", "Cluster A 3"]


def test_route_brief_reports_live_distance_jumps_and_non_fuel_arrival() -> None:
    brief = plugin_module._route_brief(
        {"system": "Destination", "targeted_fss_bodies": ["Destination A 2"]},
        {
            "Location": {"StarSystem": "Start", "StarPos": [0.0, 0.0, 0.0]},
            "NavInfo": {
                "NavRoute": [
                    {"StarSystem": "Fuel Stop", "StarPos": [3.0, 4.0, 0.0], "StarClass": "K", "Scoopable": True},
                    {"StarSystem": "Destination", "StarPos": [3.0, 4.0, 12.0], "StarClass": "L", "Scoopable": False},
                ]
            },
        },
    )

    assert brief["verified"] is True
    assert brief["destination_system"] == "Destination"
    assert brief["total_distance_ly"] == 17.0
    assert brief["jumps"] == 2
    assert brief["fuel_stars_only"] is False
    assert brief["non_fuel_stars"] == [{
        "hop": 2,
        "system": "Destination",
        "star_class": "L",
        "fuel_star": False,
    }]
    assert "À l’arrivée : étoile de classe L, non scoopable." in brief["spoken_summary_fr"]


def test_route_brief_says_only_fuel_stars_when_every_hop_is_scoopable() -> None:
    brief = plugin_module._route_brief(
        {"system": "Destination"},
        {
            "Location": {"StarSystem": "Start", "StarPos": [0.0, 0.0, 0.0]},
            "NavInfo": {
                "NavRoute": [
                    {"StarSystem": "Destination", "StarPos": [10.0, 0.0, 0.0], "StarClass": "F", "Scoopable": True},
                ]
            },
        },
    )

    assert brief["total_distance_ly"] == 10.0
    assert brief["jumps"] == 1
    assert brief["fuel_stars_only"] is True
    assert brief["spoken_summary_fr"].endswith("Que des Fuel Stars.")


def test_french_exploration_station_lookup_prefers_science_officer(tmp_path, monkeypatch) -> None:
    guide = tmp_path / "elite-hcs-astra" / "SKILL.md"
    guide.parent.mkdir(parents=True)
    guide.write_text(
        "# Crew stations\nThe documented exploration station is `science officer`; "
        "`away missions` is only the Odyssey on-foot suit station.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_module, "_knowledge_root", lambda: tmp_path)

    result = json.loads(plugin_module._guide_lookup(
        plugin_module.GuideLookupParameters(query="Quel est le nom de la station d'exploration pour Astra ?"),
        {},
    ))

    assert result["verified"] is True
    assert "science officer" in result["evidence"][0]["content"]
    assert "away missions" in result["evidence"][0]["content"]


def test_knowledge_root_prefers_explicit_environment_override(tmp_path, monkeypatch) -> None:
    explicit = tmp_path / "custom-elite-guide"
    explicit.mkdir()
    monkeypatch.setenv("COVAS_ELITE_GUIDE_PATH", str(explicit))

    assert plugin_module._knowledge_root() == explicit


def test_knowledge_root_finds_deployed_windows_guide(tmp_path, monkeypatch) -> None:
    deployed = tmp_path / "com.covas-next.ui" / "managed-guides" / "elite"
    deployed.mkdir(parents=True)
    monkeypatch.delenv("COVAS_ELITE_GUIDE_PATH", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert plugin_module._knowledge_root() == deployed


def test_knowledge_root_uses_tracked_guide_during_development(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("COVAS_ELITE_GUIDE_PATH", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setattr(plugin_module.Path, "home", classmethod(lambda cls: tmp_path / "empty-home"))
    monkeypatch.chdir(tmp_path)

    assert plugin_module._knowledge_root() == ROOT / "guides" / "elite"
