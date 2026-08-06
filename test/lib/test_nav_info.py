from src.lib.Event import GameEvent
from src.lib.projections.nav_info import NavInfo, NavRouteItem


class StubSystemDatabase:
    def get_bodies(self, _system_name: str):
        return []

    def fetch_multiple_systems_nonblocking(self, _systems):
        return None


def jump(star_system: str, *, fuel_level: float = 4.0, fuel_used: float = 4.0) -> GameEvent:
    return GameEvent(content={
        "event": "FSDJump",
        "timestamp": "2026-08-07T00:00:00Z",
        "StarSystem": star_system,
        "SystemAddress": 1,
        "FuelLevel": fuel_level,
        "FuelUsed": fuel_used,
    }, historic=False)


def event_names(events) -> list[str]:
    return [str(event.content.get("event")) for event in events]


def test_no_fuel_route_warning_when_current_arrival_star_is_scoopable() -> None:
    projection = NavInfo(StubSystemDatabase())
    projection.state.NavRoute = [
        NavRouteItem(StarSystem="Arrival", Scoopable=True, StarClass="K"),
        NavRouteItem(StarSystem="Dark 1", Scoopable=False, StarClass="Y"),
        NavRouteItem(StarSystem="Dark 2", Scoopable=False, StarClass="T"),
        NavRouteItem(StarSystem="Fuel", Scoopable=True, StarClass="M"),
    ]

    events = projection.process(jump("Arrival"))

    assert "NoScoopableStars" not in event_names(events)


def test_fuel_route_warning_remains_for_non_scoopable_arrival_with_no_reachable_fuel_star() -> None:
    projection = NavInfo(StubSystemDatabase())
    projection.state.NavRoute = [
        NavRouteItem(StarSystem="Arrival", Scoopable=False, StarClass="Y"),
        NavRouteItem(StarSystem="Dark 1", Scoopable=False, StarClass="T"),
        NavRouteItem(StarSystem="Dark 2", Scoopable=False, StarClass="L"),
        NavRouteItem(StarSystem="Fuel", Scoopable=True, StarClass="M"),
    ]

    events = projection.process(jump("Arrival"))

    assert "NoScoopableStars" in event_names(events)
