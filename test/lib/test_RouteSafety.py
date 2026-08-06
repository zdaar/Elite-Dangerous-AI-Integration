import inspect
import json

from src.lib import RouteSafety as route_safety_module
from src.lib.RouteSafety import (
    RouteSafetyPolicy,
    assess_star_system,
    filter_route_candidates,
    star_geometry_from_edsm,
    star_geometry_from_journal,
    star_geometry_from_spansh,
)
from src.lib.RouteSafetyProvider import assess_spansh_systems


def spansh_star(
    name: str,
    *,
    main: bool,
    distance: float,
    radius: float | None,
    semi_major_axis: float | None = None,
    eccentricity: float | None = None,
) -> dict:
    return {
        "type": "Star",
        "name": name,
        "subtype": "G (White-Yellow) Star",
        "is_main_star": main,
        "distance_to_arrival": distance,
        "solar_radius": radius,
        "semi_major_axis": semi_major_axis,
        "orbital_eccentricity": eccentricity,
        "orbital_period": 0.4,
        "parents": [{"Null": 0}],
    }


def geometry(*records: dict):
    return [star for record in records if (star := star_geometry_from_spansh(record))]


def test_close_binary_is_dangerous_from_shared_barycentre_periapsis() -> None:
    stars = geometry(
        spansh_star(
            "Traikaae IH-V d2-15 A",
            main=True,
            distance=0,
            radius=1.161865,
            semi_major_axis=0.003670032,
            eccentricity=0.005728,
        ),
        spansh_star(
            "Traikaae IH-V d2-15 B",
            main=False,
            distance=6.071339,
            radius=0.580872,
            semi_major_axis=0.008553299,
            eccentricity=0.005728,
        ),
    )

    assessment = assess_star_system(
        "Traikaae IH-V d2-15",
        stars,
        RouteSafetyPolicy(),
        system_id64=525638617883,
    )

    assert assessment.status == "dangerous"
    assert assessment.evidence["separation_basis"] == "shared_barycentre_periapsis"
    assert assessment.evidence["surface_gap_ls"] < assessment.evidence["maximum_allowed_surface_gap_ls"]


def test_wide_multiple_star_system_is_safe() -> None:
    stars = geometry(
        spansh_star("Wide A", main=True, distance=0, radius=0.942, semi_major_axis=0.02428, eccentricity=0.031),
        spansh_star("Wide B", main=False, distance=40, radius=0.644, semi_major_axis=0.05770, eccentricity=0.031),
    )

    assessment = assess_star_system("Wide", stars, RouteSafetyPolicy())

    assert assessment.status == "safe"
    assert assessment.evidence["safe_pairs"][0]["surface_gap_ls"] > 20


def test_single_star_system_is_safe_and_missing_geometry_is_unknown() -> None:
    single = geometry(spansh_star("Solo", main=True, distance=0, radius=1.0))
    assert assess_star_system("Solo", single, RouteSafetyPolicy()).status == "safe"

    malformed = geometry(
        spansh_star("Broken A", main=True, distance=0, radius=1.0),
        spansh_star("Broken B", main=False, distance=20, radius=None),
    )
    assert assess_star_system("Broken", malformed, RouteSafetyPolicy()).status == "unknown"
    assert assess_star_system("Missing", [], RouteSafetyPolicy()).status == "unknown"


def test_recorded_close_separation_can_prove_danger_but_not_safety() -> None:
    close = geometry(
        spansh_star("Close A", main=True, distance=0, radius=1.0),
        spansh_star("Close B", main=False, distance=5.0, radius=1.0),
    )
    far = geometry(
        spansh_star("Far A", main=True, distance=0, radius=1.0),
        spansh_star("Far B", main=False, distance=50.0, radius=1.0),
    )

    assert assess_star_system("Close", close, RouteSafetyPolicy()).status == "dangerous"
    assert assess_star_system("Far", far, RouteSafetyPolicy()).status == "unknown"


def test_edsm_and_journal_adapters_preserve_units_and_parent_identity() -> None:
    edsm = star_geometry_from_edsm({
        "type": "Star",
        "name": "EDSM A",
        "subType": "K (Yellow-Orange) Star",
        "isMainStar": True,
        "distanceToArrival": 0,
        "solarRadius": 1.0,
        "semiMajorAxis": 1.0,
        "orbitalEccentricity": 0.1,
        "orbitalPeriod": 365.0,
        "parents": [{"Null": 0}],
    })
    journal = star_geometry_from_journal({
        "BodyName": "Journal A",
        "StarType": "K",
        "DistanceFromArrivalLS": 0,
        "Radius": 695_700_000,
        "SemiMajorAxis": 149_597_870_700,
        "Eccentricity": 0.1,
        "OrbitalPeriod": 31_536_000,
        "Parents": [{"Null": 0}],
    })

    assert edsm is not None and journal is not None
    assert round(edsm.semi_major_axis_ls or 0, 3) == 499.005
    assert round(journal.semi_major_axis_ls or 0, 3) == 499.005
    assert round(journal.solar_radius or 0, 3) == 1.0
    assert edsm.immediate_parent == journal.immediate_parent == "null:0"


def test_generic_filter_supports_alternate_selection_no_route_and_two_consumers() -> None:
    policy = RouteSafetyPolicy()
    dangerous = assess_star_system(
        "Danger",
        geometry(
            spansh_star("Danger A", main=True, distance=0, radius=1.0),
            spansh_star("Danger B", main=False, distance=5.0, radius=1.0),
        ),
        policy,
        system_id64=1,
    )
    safe = assess_star_system(
        "Safe",
        geometry(spansh_star("Safe A", main=True, distance=0, radius=1.0)),
        policy,
        system_id64=2,
    )
    assessments = {1: dangerous, 2: safe}

    exobiology = filter_route_candidates(
        [{"system": "Danger", "system_id64": 1}, {"system": "Safe", "system_id64": 2}],
        assessments,
        policy,
    )
    future_mode = filter_route_candidates(
        [{"destination": "Danger", "address": 1}, {"destination": "Safe", "address": 2}],
        assessments,
        policy,
        id_getter=lambda candidate: candidate["address"],
    )
    no_route = filter_route_candidates(
        [{"system": "Danger", "system_id64": 1}],
        assessments,
        policy,
    )

    assert [item["system"] for item in exobiology.included] == ["Safe"]
    assert [item["destination"] for item in future_mode.included] == ["Safe"]
    assert no_route.included == []


def test_unknown_policy_defaults_to_allow_and_can_exclude() -> None:
    candidates = [{"system": "Unmapped", "system_id64": 9}]
    assert len(filter_route_candidates(candidates, {}, RouteSafetyPolicy()).included) == 1
    strict = filter_route_candidates(
        candidates,
        {},
        RouteSafetyPolicy(unknown_system_policy="exclude"),
    )
    assert strict.included == []
    assert strict.excluded[0]["route_safety"]["status"] == "unknown"


def test_classifier_module_has_no_network_or_llm_dependency() -> None:
    source = inspect.getsource(route_safety_module)
    for forbidden in ("import requests", "import aiohttp", "import openai", "from openai"):
        assert forbidden not in source.casefold()


def test_provider_batches_long_routes_by_exact_system_id64() -> None:
    batch_sizes: list[int] = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    def request_post(_url: str, **kwargs) -> Response:
        request = json.loads(kwargs["data"])
        system_ids = [
            int(value)
            for value in request["filters"]["system_id64"]["value"]
        ]
        batch_sizes.append(len(system_ids))
        records = []
        for system_id in system_ids:
            record = spansh_star(
                f"System {system_id} A",
                main=True,
                distance=0,
                radius=1.0,
            )
            record["system_id64"] = system_id
            records.append(record)
        return Response({"count": len(records), "results": records})

    assessments, error = assess_spansh_systems(
        {system_id: f"System {system_id}" for system_id in range(100, 126)},
        RouteSafetyPolicy(),
        request_post=request_post,
    )

    assert error is None
    assert batch_sizes == [25, 1]
    assert len(assessments) == 26
    assert all(result.status == "safe" for result in assessments.values())
