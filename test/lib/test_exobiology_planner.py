from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.actions.ExobiologyPlanner import (
    _first_discovery_request,
    _route_targets,
    current_jump_range,
    plan_exobiology,
    FIRST_DISCOVERY_PROFILES,
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


def test_confirmed_auto_plan_uses_form_route_and_returns_navigation() -> None:
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
        {"strategy": "auto"},
        {
            "Location": {"StarSystem": "Sol"},
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


def test_first_discovery_request_uses_unconfirmed_prediction_filters() -> None:
    request = _first_discovery_request(FIRST_DISCOVERY_PROFILES[0], "Sol", 2000, 8)
    filters = request["filters"]
    assert filters["landmark_value"] == {"comparison": "<=>", "value": [0, 0]}
    assert filters["genuses"]["logic"] == "and"
    assert filters["distance"] == {"min": 0, "max": 2000}
    assert request["reference_system"] == "Sol"


def test_first_discovery_plan_queries_all_three_profiles() -> None:
    requests = []

    def fake_post(url, **kwargs):
        requests.append(kwargs["json"])
        profile_number = len(requests)
        return FakeResponse({
            "results": [{
                "system_name": f"Virgin {profile_number}",
                "name": f"Virgin {profile_number} A 1",
                "distance": 100 * profile_number,
                "distance_to_arrival": 500,
                "signal_count": 8,
                "genuses": ["Stratum"],
            }]
        })

    plan = plan_exobiology(
        {"strategy": "first_discovery", "radius": 1500},
        {
            "Location": {"StarSystem": "Sol"},
            "ShipInfo": {"CurrentJumpRange": 50},
        },
        request_post=fake_post,
    )

    assert len(requests) == 3
    assert plan["strategy"] == "first_discovery"
    assert plan["recommended_target"]["first_discovery_bonus_expected"] == "possible_not_guaranteed"
    assert plan["recommended_target"]["estimated_first_logged_ceiling"] == 90_323_900 * 5
