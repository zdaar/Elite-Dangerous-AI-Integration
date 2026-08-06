import json

from src.lib.RouteBypassPlanner import find_verified_safe_bypass
from src.lib.RouteSafety import RouteSafetyPolicy
from src.lib.RouteSafetySupervisor import RouteHop


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def nearby(name: str, address: int, coords: tuple[float, float, float], *, scoopable: bool = True) -> dict:
    return {
        "name": name,
        "id64": address,
        "distance": 20,
        "coords": {"x": coords[0], "y": coords[1], "z": coords[2]},
        "coordsLocked": True,
        "primaryStar": {
            "type": "K (Yellow-Orange) Star" if scoopable else "L (Brown dwarf) Star",
            "isScoopable": scoopable,
        },
    }


def star(system_id: int, name: str) -> dict:
    return {
        "system_id64": system_id,
        "type": "Star",
        "name": f"{name} A",
        "subtype": "K (Yellow-Orange) Star",
        "is_main_star": True,
        "distance_to_arrival": 0,
        "solar_radius": 0.8,
        "parents": [{"Null": 0}],
    }


def route_hops():
    return (
        RouteHop("Boundary", 1, (0.0, 0.0, 0.0)),
        RouteHop("Danger", 2, (20.0, 0.0, 0.0)),
        RouteHop("Destination", 3, (60.0, 0.0, 0.0)),
    )


def test_bypass_prefers_a_proven_safe_kgbfoam_candidate() -> None:
    boundary, dangerous, destination = route_hops()

    def fake_get(*_args, **_kwargs):
        return FakeResponse([
            nearby("Unknown Best", 10, (35.0, 20.0, 0.0)),
            nearby("Verified Safe", 11, (30.0, 15.0, 0.0)),
            nearby("Brown Dwarf", 12, (25.0, 25.0, 0.0), scoopable=False),
        ])

    def fake_post(_url, **kwargs):
        request = json.loads(kwargs["data"])
        assert set(request["filters"]["system_id64"]["value"]) == {"10", "11"}
        return FakeResponse({"count": 1, "results": [star(11, "Verified Safe")]})

    candidate, error = find_verified_safe_bypass(
        boundary,
        dangerous,
        destination,
        50,
        {2},
        RouteSafetyPolicy(),
        request_get=fake_get,
        request_post=fake_post,
    )

    assert error is None
    assert candidate is not None
    assert candidate.hop.name == "Verified Safe"
    assert candidate.safety_status == "safe"
    assert candidate.primary_star_type.startswith("K")


def test_bypass_uses_scoopable_unknown_with_explicit_warning_when_needed() -> None:
    boundary, dangerous, destination = route_hops()

    candidate, warning = find_verified_safe_bypass(
        boundary,
        dangerous,
        destination,
        50,
        {2},
        RouteSafetyPolicy(),
        request_get=lambda *_args, **_kwargs: FakeResponse([
            nearby("Unknown Bypass", 10, (30.0, 20.0, 0.0)),
        ]),
        request_post=lambda *_args, **_kwargs: FakeResponse({"count": 0, "results": []}),
    )

    assert candidate is not None
    assert candidate.hop.name == "Unknown Bypass"
    assert candidate.safety_status == "unknown"
    assert "No positively safe" in str(warning)


def test_bypass_returns_no_route_when_only_non_scoopable_or_out_of_range() -> None:
    boundary, dangerous, destination = route_hops()
    candidate, error = find_verified_safe_bypass(
        boundary,
        dangerous,
        destination,
        30,
        {2},
        RouteSafetyPolicy(),
        request_get=lambda *_args, **_kwargs: FakeResponse([
            nearby("Brown", 10, (10.0, 5.0, 0.0), scoopable=False),
            nearby("Too Far", 11, (50.0, 0.0, 0.0)),
        ]),
        request_post=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no star query expected")),
    )

    assert candidate is None
    assert "No scoopable" in str(error)
