import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.actions.ExobiologyPlanner import (
    FIRST_DISCOVERY_PROFILES,
    PRE_ODYSSEY_CUTOFF,
    _first_discovery_request,
    _group_stratum_targets,
    _is_tectonicas_compatible,
    _route_targets,
    current_jump_range,
    plan_exobiology,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.reason = "OK"
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def old_hmc_body(
    system: str,
    body: str,
    coordinates: tuple[float, float, float],
    *,
    arrival_ls: float = 500,
    atmosphere: str = "Thin Carbon dioxide",
    gravity: float = 0.30,
    temperature: float = 220,
) -> dict:
    return {
        "system_name": system,
        "name": body,
        "body_id": 2,
        "subtype": "High metal content world",
        "atmosphere": atmosphere,
        "gravity": gravity,
        "surface_temperature": temperature,
        "distance_to_arrival": arrival_ls,
        "distance": 20,
        "system_x": coordinates[0],
        "system_y": coordinates[1],
        "system_z": coordinates[2],
        "updated_at": "2020-07-13 16:23:39+00",
        "volcanism_type": "No volcanism",
    }


def test_current_jump_range_prefers_live_ship_value() -> None:
    states = {
        "ShipInfo": {
            "CurrentJumpRange": 62.4,
            "MaximumJumpRange": 70.0,
            "ReportedMaximumJumpRange": 68.0,
        },
        "Loadout": {"MaxJumpRange": 67.0},
    }
    assert current_jump_range(states) == 62.4


def test_route_ranking_penalizes_extreme_supercruise() -> None:
    route = [
        {"name": "Sol", "x": 0, "y": 0, "z": 0},
        {
            "name": "Far Cruise",
            "x": 10,
            "y": 0,
            "z": 0,
            "bodies": [{
                "name": "Far Cruise A 1",
                "distance_to_arrival": 4_000_000,
                "landmark_value": 40_000_000,
                "landmarks": [{"subtype": "Stratum Tectonicas", "value": 19_010_800}],
            }],
        },
        {
            "name": "Fast Target",
            "x": 40,
            "y": 0,
            "z": 0,
            "bodies": [{
                "name": "Fast Target 2",
                "distance_to_arrival": 50,
                "landmark_value": 20_000_000,
                "landmarks": [{"subtype": "Stratum Tectonicas", "value": 19_010_800}],
            }],
        },
    ]
    targets = _route_targets(route, 55)
    assert targets[0]["body"] == "Fast Target 2"
    assert targets[0]["estimated_credits_per_hour"] > targets[1]["estimated_credits_per_hour"]


def test_explicit_throughput_keeps_deterministic_exomastery_route() -> None:
    posted = []

    def fake_post(url, **kwargs):
        posted.append((url, kwargs))
        return FakeResponse({"job": "job-1"}, status_code=202)

    def fake_get(url, **kwargs):
        return FakeResponse({
            "state": "completed",
            "result": [
                {"name": "Sol", "x": 0, "y": 0, "z": 0},
                {
                    "name": "Target System",
                    "x": 30,
                    "y": 0,
                    "z": 0,
                    "bodies": [{
                        "name": "Target System A 2",
                        "distance_to_arrival": 100,
                        "landmark_value": 30_000_000,
                        "landmarks": [{"subtype": "Stratum Tectonicas", "value": 19_010_800}],
                    }],
                },
            ],
        })

    plan = plan_exobiology(
        {"strategy": "throughput"},
        {
            "Location": {"StarSystem": "Sol", "StarPos": [0, 0, 0]},
            "ShipInfo": {"CurrentJumpRange": 55},
        },
        request_post=fake_post,
        request_get=fake_get,
        sleep=lambda _: None,
    )

    assert posted[0][1]["data"]["from"] == "Sol"
    assert posted[0][1]["data"]["range"] == "55.0"
    assert "json" not in posted[0][1]
    assert plan["strategy"] == "confirmed_throughput"
    assert plan["navigation_instruction"] == {
        "system": "Target System",
        "body": "Target System A 2",
    }


def test_stratum_request_uses_old_hmc_records_and_omits_false_negative_filters() -> None:
    request = _first_discovery_request(
        FIRST_DISCOVERY_PROFILES[0],
        "Sol",
        500,
        100,
        reference_coords={"x": 1.0, "y": 2.0, "z": 3.0},
        max_arrival_ls=1800,
    )
    filters = request["filters"]

    assert filters["subtype"] == {"value": ["High metal content world"]}
    assert filters["updated_at"]["value"][1] == PRE_ODYSSEY_CUTOFF
    assert filters["distance_to_arrival"] == {
        "comparison": "<=>",
        "value": [0, 1800],
    }
    assert filters["distance"] == {"min": 0, "max": 500}
    for forbidden in ("is_landable", "genuses", "signals", "landmark_value"):
        assert forbidden not in filters
    assert request["reference_coords"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert "reference_system" not in request


def test_auto_posts_raw_json_and_works_with_unknown_system_name_via_starpos() -> None:
    posted = []

    def fake_post(url, **kwargs):
        posted.append((url, kwargs))
        return FakeResponse({
            "count": 2,
            "results": [
                old_hmc_body("Far Cluster", "Far Cluster A 2", (3_120, 0, 0)),
                old_hmc_body("Long Cruise", "Long Cruise 9", (3_130, 0, 0), arrival_ls=20_000),
            ],
        })

    plan = plan_exobiology(
        {"strategy": "auto", "radius": 500, "max_arrival_ls": 1500},
        {
            "Location": {"StarSystem": "Unknown", "StarPos": [3_100, 0, 0]},
            "ShipInfo": {"CurrentJumpRange": 50},
        },
        request_post=fake_post,
    )

    kwargs = posted[0][1]
    assert "json" not in kwargs
    assert isinstance(kwargs["data"], str)
    payload = json.loads(kwargs["data"])
    assert payload["size"] == 100
    assert payload["reference_coords"] == {"x": 3100.0, "y": 0.0, "z": 0.0}
    assert payload["filters"]["distance_to_arrival"]["value"] == [0, 1500]
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded; charset=UTF-8"
    assert plan["source_system"] == "Unknown"
    assert plan["strategy"] == "stratum_sniping"
    assert plan["navigation_instruction"] == {"system": "Far Cluster"}
    assert plan["targeted_fss_bodies"] == ["Far Cluster A 2"]
    assert plan["compatible_candidate_bodies"] == 1


def test_auto_moves_search_center_outward_without_creating_an_unrouteable_leg() -> None:
    captured = []

    def fake_post(url, **kwargs):
        captured.append(json.loads(kwargs["data"]))
        return FakeResponse({
            "results": [old_hmc_body("Outer Target", "Outer Target 4", (2_600, 0, 0))],
        })

    plan = plan_exobiology(
        {"strategy": "auto"},
        {
            "Location": {"StarSystem": "Known Locally", "StarPos": [1_800, 0, 0]},
            "ShipInfo": {"CurrentJumpRange": 60},
        },
        request_post=fake_post,
    )

    # Stage the search outward without ever returning a body more than 900 ly
    # from the live position. This keeps the resulting leg routeable even when
    # Elite is still configured for economical routing.
    assert captured[0]["reference_coords"] == {"x": 2200.0, "y": 0.0, "z": 0.0}
    assert plan["outward_staging_applied"] is True
    assert plan["recommended_target"]["distance_ly"] == 800.0
    assert plan["recommended_target"]["distance_from_sol_ly"] == 2600.0
    assert plan["recommended_target"]["confidence_tier"] == "medium"


def test_outward_staging_clamps_a_large_requested_radius_to_a_routeable_sphere() -> None:
    captured = []

    def fake_post(url, **kwargs):
        captured.append(json.loads(kwargs["data"]))
        return FakeResponse({
            "results": [old_hmc_body("Staged Target", "Staged Target 2", (2_650, 0, 0))],
        })

    plan = plan_exobiology(
        {"strategy": "auto", "radius": 5_000},
        {
            "Location": {"StarSystem": "Known Locally", "StarPos": [1_800, 0, 0]},
            "ShipInfo": {"CurrentJumpRange": 60},
        },
        request_post=fake_post,
    )

    assert captured[0]["filters"]["distance"] == {"min": 0, "max": 800}
    assert captured[0]["reference_coords"] == {"x": 1900.0, "y": 0.0, "z": 0.0}
    assert plan["requested_radius_ly"] == 5_000
    assert plan["radius_ly"] == 800
    assert plan["recommended_target"]["distance_ly"] == 850.0


def test_stratum_post_filter_applies_atmosphere_specific_ranges() -> None:
    assert _is_tectonicas_compatible(
        old_hmc_body("A", "A 1", (3000, 0, 0), atmosphere="Thin Sulphur dioxide", gravity=0.4, temperature=250)
    )
    assert not _is_tectonicas_compatible(
        old_hmc_body("A", "A 2", (3000, 0, 0), atmosphere="Thin Sulphur dioxide", gravity=0.2, temperature=250)
    )
    assert _is_tectonicas_compatible(
        old_hmc_body("A", "A 3", (3000, 0, 0), atmosphere="Thin Water", gravity=0.05, temperature=200)
    )
    assert not _is_tectonicas_compatible(
        old_hmc_body("A", "A 4", (3000, 0, 0), atmosphere="Thin Carbon dioxide", gravity=0.3, temperature=150)
    )

    allowed = old_hmc_body("F Star", "F Star 2", (3000, 0, 0))
    allowed["parents"] = [{"type": "Star", "subtype": "F (White) Star"}]
    excluded = old_hmc_body("G Star", "G Star 2", (3000, 0, 0))
    excluded["parents"] = [{"type": "Star", "subtype": "G (White-Yellow) Star"}]
    assert _is_tectonicas_compatible(allowed)
    assert not _is_tectonicas_compatible(excluded)


def test_multiple_bodies_are_clustered_ranked_and_preserve_exact_names() -> None:
    bodies = [
        old_hmc_body("Cluster", "Cluster A 3", (3_080, 0, 0), arrival_ls=700),
        old_hmc_body("Cluster", "Cluster A 2", (3_080, 0, 0), arrival_ls=200),
        old_hmc_body("Singleton", "Singleton 1", (3_010, 0, 0), arrival_ls=200),
        old_hmc_body("Next Cluster", "Next Cluster 4", (3_090, 0, 0), arrival_ls=200),
    ]

    targets = _group_stratum_targets(
        bodies,
        source_coords={"x": 3_000.0, "y": 0.0, "z": 0.0},
        jump_range=50,
    )

    assert targets[0]["system"] == "Cluster"
    assert targets[0]["candidate_body_count"] == 2
    assert [body["body"] for body in targets[0]["bodies"]] == [
        "Cluster A 2",
        "Cluster A 3",
    ]
    assert targets[0]["body"] == "Cluster A 2"
    assert targets[0]["route_order"] == 1
    # Greedy routing chooses the nearby system after the first high-value cluster.
    assert targets[1]["system"] == "Next Cluster"
    assert targets[1]["route_leg_distance_ly"] == 10.0


def test_near_bubble_candidates_are_explicitly_low_confidence() -> None:
    targets = _group_stratum_targets(
        [old_hmc_body("Busy Space", "Busy Space 2", (1_500, 0, 0))],
        source_coords={"x": 1_400.0, "y": 0.0, "z": 0.0},
        jump_range=50,
    )
    assert targets[0]["confidence_tier"] == "low"
    assert "false positives" in targets[0]["confidence"]
    assert targets[0]["first_discovery_bonus_expected"] == "heuristic_not_guaranteed"


def test_auto_contract_requires_targeted_fss_not_full_system_scan() -> None:
    def fake_post(url, **kwargs):
        return FakeResponse({
            "results": [old_hmc_body("Target", "Target A 2", (3_100, 0, 0))],
        })

    plan = plan_exobiology(
        {"strategy": "first_discovery"},
        {
            "Location": {"StarSystem": "Start", "StarPos": [3_000, 0, 0]},
            "ShipInfo": {"CurrentJumpRange": 50},
        },
        request_post=fake_post,
    )

    instructions = " ".join(plan["operational_notes"]).casefold()
    assert "do not fss the whole system" in instructions
    assert "resolve only the listed hmc" in instructions
    assert "do not complete the full-system fss" in plan["recommended_target"]["targeted_fss_instruction"].casefold()
    assert plan["navigation_instruction"] == {"system": "Target"}


def test_named_system_is_fallback_when_starpos_is_unavailable() -> None:
    captured = []

    def fake_post(url, **kwargs):
        captured.append(json.loads(kwargs["data"]))
        return FakeResponse({"results": []})

    plan_exobiology(
        {"strategy": "auto"},
        {"Location": {"StarSystem": "Sol"}},
        request_post=fake_post,
    )

    assert captured[0]["reference_system"] == "Sol"
    assert "reference_coords" not in captured[0]
    assert captured[0]["filters"]["distance_to_arrival"]["value"] == [0, 1700]
