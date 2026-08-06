import json
import importlib
from pathlib import Path
import sys

from openai.types.chat import ChatCompletionMessageFunctionToolCall

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.actions import actions_web


class FakePromptGenerator:
    def generate_status_message(self, projected_states: dict) -> str:
        return "status"


class FakeLLMModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list, tools: list, tool_choice: str):
        self.calls += 1
        if self.calls == 1:
            return "", [ChatCompletionMessageFunctionToolCall(
                type="function",
                id="internal_call_1",
                function={
                    "name": "get_galnet_news",
                    "arguments": json.dumps({"query": "thargoids"}),
                },
            )], {}
        return "Final report", None, {}


class FailingLLMModel:
    def generate(self, messages: list, tools: list, tool_choice: str):
        raise RuntimeError("model unavailable")


def consume_generator(generator):
    values = []
    while True:
        try:
            values.append(next(generator))
        except StopIteration as stop:
            return values, stop.value


def test_web_search_agent_yields_internal_tool_processing_events(monkeypatch) -> None:
    monkeypatch.setattr(actions_web, "get_galnet_news", lambda args, projected_states: "news result")

    updates, final_result = consume_generator(actions_web.web_search_agent(
        {"query": "latest thargoid news"},
        {},
        prompt_generator=FakePromptGenerator(),
        llm_model=FakeLLMModel(),
        max_loops=3,
    ))

    assert updates == [
        {
            "status": "searching",
            "query": "latest thargoid news",
        },
        {
            "status": "started",
            "query": "latest thargoid news",
            "iteration": 1,
            "internal_tool_call_id": "internal_call_1",
            "internal_tool_name": "get_galnet_news",
            "arguments": {"query": "thargoids"},
        },
        {
            "status": "completed",
            "query": "latest thargoid news",
            "iteration": 1,
            "internal_tool_call_id": "internal_call_1",
            "internal_tool_name": "get_galnet_news",
            "result": "news result",
        },
    ]
    assert final_result == "Final report"


def test_web_search_agent_returns_actionable_loop_error() -> None:
    updates, final_result = consume_generator(actions_web.web_search_agent(
        {"query": "search for aluminum"},
        {},
        prompt_generator=FakePromptGenerator(),
        llm_model=FailingLLMModel(),
        max_loops=3,
    ))

    assert updates == [{"status": "searching", "query": "search for aluminum"}]
    assert final_result == (
        "Web search failed while requesting the search agent model response "
        "on iteration 1 for query 'search for aluminum'. RuntimeError: model unavailable"
    )


def test_blueprint_finder_handles_default_inventory_states() -> None:
    projected_states = {
        "Materials": {
            "Raw": [{"Name": "carbon", "Count": 0, "Name_Localised": None}],
            "Manufactured": [],
            "Encoded": [],
        },
        "ShipLocker": {
            "Items": None,
            "Components": None,
            "Data": None,
            "Consumables": None,
        },
    }

    result = actions_web.blueprint_finder({
        "modifications": ["Extra Backpack Capacity"],
    }, projected_states)

    assert "Extra Backpack Capacity" in result
    assert actions_web.material_finder({}, projected_states) == "No materials found"


def test_plot_name_match_score_prefers_exact_match() -> None:
    assert actions_web.plot_name_match_score("Sol", "Sol") == 1.0
    assert actions_web.plot_name_match_score("Jameson Memorial", "jameson memorial") == 1.0
    assert actions_web.plot_name_match_score("HIP 58412 8 D", "HIP584128D") == 1.0
    assert actions_web.plot_name_match_score("Sol", "Alpha Centauri") == 0.0
    assert actions_web.is_plot_name_exact_match("Earth", "Earth") is True
    assert actions_web.is_plot_name_exact_match("Earth", "Earth Expeditionary Fleet 4") is False


def test_select_best_plot_target_prefers_exact_match_over_fuzzy() -> None:
    candidates = [
        actions_web.ResolvedPlotTarget(
            target_type="body",
            name="Earth Expeditionary Fleet 4",
            system_name="Earth Expeditionary Fleet",
            system_map_category="LANDFALL PLANETS",
            distance=22032.0,
            match_score=0.9,
            details={},
            is_landable=True,
        ),
        actions_web.ResolvedPlotTarget(
            target_type="body",
            name="Earth",
            system_name="Sol",
            system_map_category="LANDFALL PLANETS",
            distance=0.0,
            match_score=1.0,
            details={},
            is_landable=False,
        ),
    ]

    best_match = actions_web._select_best_plot_target(candidates, "Earth")
    assert best_match is not None
    assert best_match.name == "Earth"
    assert best_match.system_name == "Sol"


def test_select_best_plot_target_uses_match_score_then_distance() -> None:
    candidates = [
        actions_web.ResolvedPlotTarget(
            target_type="system",
            name="Sol",
            system_name="Sol",
            system_map_category=None,
            distance=10.0,
            match_score=0.7,
            details={},
        ),
        actions_web.ResolvedPlotTarget(
            target_type="station",
            name="Jameson Memorial",
            system_name="Shinrarta Dezhra",
            system_map_category="ORBITAL PORTS",
            distance=5.0,
            match_score=1.0,
            details={},
        ),
    ]

    best_match = actions_web._select_best_plot_target(candidates, "Jameson Memorial")
    assert best_match is not None
    assert best_match.name == "Jameson Memorial"


def test_system_map_category_for_station_uses_spansh_types() -> None:
    assert actions_web.system_map_category_for_station({"type": "Coriolis Starport"}) == "ORBITAL PORTS"
    assert actions_web.system_map_category_for_station({"type": "Planetary Outpost"}) == "PLANETARY PORTS"
    assert actions_web.system_map_category_for_station({"type": "Drake-Class Carrier"}) == "FLEET CARRIERS"
    assert actions_web.system_map_category_for_station({"type": "Mega ship"}) == "INSTALLATIONS"
    assert actions_web.system_map_category_for_station({"type": "Surface Settlement"}) == "SURFACE SETTLEMENTS"
    assert actions_web.system_map_category_for_station({"type": "Settlement"}) == "ODYSSEY SETTLEMENTS"
    assert actions_web.system_map_category_for_station({"type": "Unknown Type"}) is None


def test_ensure_in_system_plot_target_rejects_unlandable_body() -> None:
    target = actions_web.ResolvedPlotTarget(
        target_type="body",
        name="Earth",
        system_name="Sol",
        system_map_category="LANDFALL PLANETS",
        distance=0.0,
        match_score=1.0,
        details={"is_landable": False},
        is_landable=False,
    )

    try:
        actions_web.ensure_in_system_plot_target(target)
    except Exception as error:
        assert "not landable" in str(error)
    else:
        raise AssertionError("Expected unlandable body to be rejected")


def test_plot_candidates_from_bodies_skips_non_planets_and_preserves_exact_name(monkeypatch) -> None:
    captured_sizes: list[int] = []
    captured_names: list[str] = []
    captured_requests: list[dict] = []

    def fake_prepare_body_request(obj, projected_states):
        captured_sizes.append(obj["size"])
        captured_names.append(obj["name"])
        return {"filters": {}, "size": obj["size"], "page": 0}

    def fake_post(url: str, request_body: dict) -> dict:
        captured_requests.append(request_body)
        return {
            "results": [
                {
                    "name": "Earth Expeditionary Fleet",
                    "system_name": "Earth Expeditionary Fleet",
                    "type": "Star",
                    "distance": 22032.0,
                    "is_landable": False,
                },
                {
                    "name": "Earth",
                    "system_name": "Sol",
                    "type": "Planet",
                    "distance": 0.0,
                    "is_landable": False,
                },
            ]
        }

    monkeypatch.setattr(actions_web, "prepare_body_request", fake_prepare_body_request)
    monkeypatch.setattr(actions_web, "_spansh_post", fake_post)

    candidates = actions_web._plot_candidates_from_bodies("Earth", {
        "Location": {
            "StarSystem": "Sol",
            "StarPos": [0, 0, 0],
        }
    })

    assert captured_sizes == [10]
    assert captured_names == ["Earth"]
    assert captured_requests[0]["size"] == 10
    assert captured_requests[0]["sort"] == [{"distance": {"direction": "asc"}}]
    assert captured_requests[0]["reference_coords"] == {"x": 0, "y": 0, "z": 0}
    assert len(candidates) == 1
    assert candidates[0].name == "Earth"
    assert candidates[0].is_landable is False


def test_plot_candidates_from_stations_requests_nearest_named_station(monkeypatch) -> None:
    captured_requests: list[dict] = []

    def fake_prepare_station_request(obj, projected_states):
        return {
            "filters": {
                "distance": {"min": "0", "max": "50000"},
                "name": {"value": obj["name"]},
                "type": {"value": ["Outpost"]},
                "has_large_pad": {"value": True},
            },
            "sort": [],
            "size": obj["size"],
            "page": 0,
        }

    def fake_post(url: str, request_body: dict) -> dict:
        captured_requests.append(request_body)
        return {
            "results": [{
                "name": "Moskowitz Enterprise",
                "system_name": "Lyncis Sector XK-O b6-1",
                "type": "Outpost",
                "distance": 12.0,
            }]
        }

    monkeypatch.setattr(actions_web, "prepare_station_request", fake_prepare_station_request)
    monkeypatch.setattr(actions_web, "_spansh_post", fake_post)

    candidates = actions_web._plot_candidates_from_stations("Moskowitz Enterprise", {
        "Location": {
            "StarSystem": "Lyncis Sector XK-O b6-1",
            "StarPos": [-82.625, 75.84375, -79.46875],
        }
    })

    assert captured_requests[0] == {
        "filters": {
            "distance": {"min": "0", "max": "50000"},
            "name": {"value": "Moskowitz Enterprise"},
        },
        "sort": [{"distance": {"direction": "asc"}}],
        "size": 10,
        "page": 0,
        "reference_coords": {
            "x": -82.625,
            "y": 75.84375,
            "z": -79.46875,
        },
    }
    assert len(candidates) == 1
    assert candidates[0].name == "Moskowitz Enterprise"


def test_plot_search_query_prefers_station_then_body_then_system() -> None:
    assert actions_web.plot_search_query(station="Jameson Memorial", body="Earth", system="Sol") == "Jameson Memorial"
    assert actions_web.plot_search_query(body="Earth", system="Sol") == "Earth"
    assert actions_web.plot_search_query(system="Sol") == "Sol"
    assert actions_web.plot_search_query() is None


def test_spansh_plot_search_name_preserves_procedural_suffix() -> None:
    assert actions_web.spansh_plot_search_name("Earth") == "Earth"
    assert actions_web.spansh_plot_search_name("Synuefue KG-T c5-0") == "Synuefue KG-T c5-0"
    assert actions_web.spansh_plot_search_name("A") == "A"
    assert actions_web.spansh_plot_search_name("") == ""
    assert actions_web._plot_search_obj("Jameson Memorial") == {
        "name": "Jameson Memorial",
        "size": 10,
    }


def test_station_request_excludes_carriers_and_includes_planetary_stations_by_default() -> None:
    request = actions_web.prepare_station_request({}, {})

    assert "Drake-Class Carrier" not in request["filters"]["type"]["value"]
    assert "is_planetary" not in request["filters"]


def test_station_request_includes_carriers_and_excludes_planetary_stations() -> None:
    request = actions_web.prepare_station_request({
        "include_player_fleetcarrier": True,
        "include_planetary_stations": False,
    }, {})

    assert request["filters"]["type"]["value"][-1] == "Drake-Class Carrier"
    assert request["filters"]["is_planetary"] == {"value": False}


def test_station_request_serializes_required_services_as_combined_intersection() -> None:
    request = actions_web.prepare_station_request({
        "services": [
            {"name": "Universal Cartographics"},
            {"name": "Vista Genomics"},
        ],
    }, {})

    assert request["filters"]["services"] == [
        {"name": ["Universal Cartographics"]},
        {"name": ["Vista Genomics"]},
    ]


def test_station_response_rejects_partial_service_matches_and_exclusions() -> None:
    request = {
        "filters": {
            "services": [
                {"name": ["Universal Cartographics"]},
                {"name": ["Vista Genomics"]},
            ],
        },
    }
    response = {
        "count": 3,
        "size": 3,
        "results": [
            {
                "name": "Cartographics Only",
                "system_name": "Open System",
                "distance": 1,
                "distance_to_arrival": 10,
                "is_planetary": False,
                "services": [{"name": "Universal Cartographics"}],
            },
            {
                "name": "Excluded Exact Match",
                "system_name": "Permit System",
                "distance": 2,
                "distance_to_arrival": 20,
                "is_planetary": False,
                "services": [
                    {"name": "Universal Cartographics"},
                    {"name": "Vista Genomics"},
                ],
            },
            {
                "name": "Valid Exact Match",
                "system_name": "Open System",
                "distance": 3,
                "distance_to_arrival": 30,
                "is_planetary": False,
                "services": [
                    {"name": "Universal Cartographics"},
                    {"name": "Vista Genomics"},
                ],
            },
        ],
    }

    filtered = actions_web.filter_station_response(
        request,
        response,
        local_filters={"exclude_systems": ["Permit System"]},
    )

    assert [result["name"] for result in filtered["results"]] == ["Valid Exact Match"]
    assert filtered["amount_total"] == 1
    assert filtered["required_services"] == ["Universal Cartographics", "Vista Genomics"]
    assert filtered["service_match"] == "all"


def test_station_request_uses_default_commodity_market_data_age() -> None:
    request = actions_web.prepare_station_request({
        "commodities": [{"name": "Tritium", "amount": 100, "transaction": "Buy"}],
    }, {})

    assert request["filters"]["market_updated_at"] == {
        "comparison": "<=>",
        "value": ["now-2d", "now"],
    }


def test_station_request_uses_requested_commodity_market_data_age() -> None:
    request = actions_web.prepare_station_request({
        "commodities": [{"name": "Tritium", "amount": 100, "transaction": "Buy"}],
        "market_days_old": 7,
    }, {})

    assert request["filters"]["market_updated_at"]["value"] == ["now-7d", "now"]


def test_station_request_rejects_invalid_commodity_market_data_age() -> None:
    try:
        actions_web.prepare_station_request({
            "commodities": [{"name": "Tritium", "amount": 100, "transaction": "Buy"}],
            "market_days_old": 0,
        }, {})
    except Exception as error:
        assert str(error) == "market_days_old must be a positive whole number."
    else:
        raise AssertionError("Expected an invalid market data age to be rejected")


def test_station_response_reports_effective_commodity_market_data_age() -> None:
    response = actions_web.filter_station_response({
        "filters": {
            "market": [{"name": "Tritium"}],
            "market_updated_at": {"comparison": "<=>", "value": ["now-7d", "now"]},
        },
    }, {
        "count": 1,
        "size": 1,
        "results": [{
            "name": "Test Station",
            "system_name": "Sol",
            "distance": 0,
            "distance_to_arrival": 10,
            "is_planetary": False,
            "services": [],
            "market": [],
        }],
    })

    assert response["market_data_max_age_days"] == 7


def test_resolve_plot_target_queries_all_spansh_endpoints(monkeypatch) -> None:
    posted_urls: list[str] = []

    def fake_post(url: str, request_body: dict) -> dict:
        posted_urls.append(url)
        assert request_body["size"] == 10
        assert request_body["sort"] == [{"distance": {"direction": "asc"}}]
        assert request_body["reference_system"] == "Alpha Centauri"
        if url == actions_web.SPANSH_SYSTEMS_URL:
            return {"results": [{"name": "Sol", "distance": 100.0}]}
        if url == actions_web.SPANSH_STATIONS_URL:
            return {"results": []}
        if url == actions_web.SPANSH_BODIES_URL:
            return {"results": []}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(actions_web, "_spansh_post", fake_post)

    resolved = actions_web.resolve_plot_target("Sol", projected_states={"Location": {"StarSystem": "Alpha Centauri"}})

    assert sorted(posted_urls) == sorted([
        actions_web.SPANSH_BODIES_URL,
        actions_web.SPANSH_STATIONS_URL,
        actions_web.SPANSH_SYSTEMS_URL,
    ])
    assert resolved is not None
    assert resolved.target_type == "system"
    assert resolved.system_name == "Sol"


def test_typed_system_lookup_rejects_suffix_neighbor_and_skips_other_endpoints(monkeypatch) -> None:
    posted_urls: list[str] = []
    captured_name_filters: list[str] = []

    def fake_post(url: str, request_body: dict) -> dict:
        posted_urls.append(url)
        captured_name_filters.append(request_body["filters"]["name"]["value"])
        return {"results": [{"name": "Synuefue KG-T c5-1", "distance": 0.0}]}

    monkeypatch.setattr(actions_web, "_spansh_post", fake_post)

    resolved = actions_web.lookup_plot_target(
        system="Synuefue KG-T c5-0",
        projected_states={"Location": {"StarSystem": "Synuefue KG-T c5-1"}},
    )

    assert posted_urls == [actions_web.SPANSH_SYSTEMS_URL]
    assert captured_name_filters == ["Synuefue KG-T c5-0"]
    assert resolved is None


def test_typed_system_lookup_selects_only_exact_procedural_name(monkeypatch) -> None:
    def fake_post(url: str, request_body: dict) -> dict:
        assert url == actions_web.SPANSH_SYSTEMS_URL
        return {"results": [
            {"name": "Synuefue KG-T c5-1", "distance": 0.0},
            {"name": "Synuefue KG-T c5-0", "distance": 12.0},
        ]}

    monkeypatch.setattr(actions_web, "_spansh_post", fake_post)

    resolved = actions_web.lookup_plot_target(
        system="Synuefue KG-T c5-0",
        projected_states={"Location": {"StarSystem": "Synuefue KG-T c5-1"}},
    )

    assert resolved is not None
    assert resolved.target_type == "system"
    assert resolved.system_name == "Synuefue KG-T c5-0"


def test_plot_uses_unchanged_system_without_spansh_resolution(monkeypatch) -> None:
    plotter_module = importlib.import_module("src.lib.actions.Plotter")
    monkeypatch.setattr(plotter_module, "set_game_window_active", lambda: None)

    def prepare_system(obj, _states):
        return {
            "filters": {"name": {"value": obj["name"]}},
            "sort": [],
            "size": obj["size"],
            "page": 0,
        }

    spansh_calls: list[str] = []

    def unexpected_spansh(url, _request):
        spansh_calls.append(url)
        return {"results": [{"name": "Synuefue KG-T c5-1", "distance": 0.0}]}

    plotter = actions_web.Plotter(
        prepare_system_request=prepare_system,
        spansh_post=unexpected_spansh,
    )
    plotted_systems: list[str] = []

    def fake_plot(system_name, _details, _states, _key="GalaxyMapOpen", **_kwargs):
        plotted_systems.append(system_name)
        return f"Failed to plot a route to {system_name}"

    monkeypatch.setattr(plotter, "_plot_galaxy_route", fake_plot)

    result = plotter.plot_to_target(
        {"system": "Synuefue KG-T c5-0"},
        {
            "Location": {"StarSystem": "Synuefue KG-T c5-1"},
            "NavInfo": {"NavRoute": []},
        },
    )

    assert spansh_calls == []
    assert plotted_systems == ["Synuefue KG-T c5-0"]
    assert result == "Failed to plot a route to Synuefue KG-T c5-0"
