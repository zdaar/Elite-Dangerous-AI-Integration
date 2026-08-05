import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from ..Projections import get_state_dict


SPANSH_BODIES_URL = "https://spansh.co.uk/api/bodies/search"
SPANSH_EXOBIOLOGY_ROUTE_URL = "https://spansh.co.uk/api/exobiology/route"
SPANSH_RESULTS_URL = "https://spansh.co.uk/api/results/{job_id}"
USER_AGENT = "COVAS-NEXT/exobiology-planner"

# The last day before Odyssey made thin-atmosphere worlds landable.  A body
# record older than this is useful as a *lead*, because it may not have been
# revisited since Odyssey.  It is not proof of First Footfall or First Logged.
PRE_ODYSSEY_CUTOFF = "2021-05-18T23:59:59.999Z"
SPANSH_DATA_START = "2014-12-16T00:00:00.000Z"
TECTONICAS_BASE_VALUE = 19_010_800
TECTONICAS_FIRST_LOGGED_VALUE = TECTONICAS_BASE_VALUE * 5
HIGH_CONFIDENCE_DISTANCE_FROM_SOL_LY = 3_000.0
MEDIUM_CONFIDENCE_DISTANCE_FROM_SOL_LY = 2_000.0
DEFAULT_STRATUM_RADIUS_LY = 500
DEFAULT_MAX_ARRIVAL_LS = 1_700


TECTONICAS_ATMOSPHERES = (
    "Hot thin Carbon dioxide",
    "Hot thin Sulphur dioxide",
    "Thin Carbon dioxide",
    "Thin Carbon dioxide-rich",
    "Thin Sulphur dioxide",
    "Thin Water",
    "Thin Water-rich",
    "Thin Oxygen",
    "Thin Ammonia",
    "Thin Ammonia and Oxygen",
    "Thin Ammonia-rich",
    "Thin Argon",
    "Thin Argon-rich",
)


@dataclass(frozen=True)
class ExobiologyProfile:
    name: str
    expected_base_value: int
    filters: dict[str, Any]


FIRST_DISCOVERY_PROFILES = (
    ExobiologyProfile(
        name="pre_odyssey_stratum_sniping",
        expected_base_value=TECTONICAS_BASE_VALUE,
        filters={
            "subtype": {"value": ["High metal content world"]},
            "atmosphere": {"value": list(TECTONICAS_ATMOSPHERES)},
            # Broad universal envelope.  Atmosphere-specific rules are applied
            # to the returned records below because Spansh cannot express the
            # required OR-of-ranges in a single search.
            "gravity": {"comparison": "<=>", "value": [0.035, 0.62]},
            "surface_temperature": {"comparison": "<=>", "value": [0, 450]},
        },
    ),
)


def current_system(projected_states: Any) -> str:
    location = get_state_dict(projected_states, "Location")
    system = str(location.get("StarSystem") or "").strip()
    if not system or system.casefold() == "unknown":
        raise ValueError("Current system is unknown; wait for a Location or FSDJump journal event.")
    return system


def current_coordinates(projected_states: Any) -> dict[str, float] | None:
    location = get_state_dict(projected_states, "Location")
    star_pos = location.get("StarPos")
    if not isinstance(star_pos, (list, tuple)) or len(star_pos) < 3:
        return None
    coordinates = star_pos[:3]
    if not all(
        isinstance(value, (int, float)) and math.isfinite(float(value))
        for value in coordinates
    ):
        return None
    return {
        "x": float(coordinates[0]),
        "y": float(coordinates[1]),
        "z": float(coordinates[2]),
    }


def current_jump_range(projected_states: Any) -> float:
    ship = get_state_dict(projected_states, "ShipInfo")
    loadout = get_state_dict(projected_states, "Loadout")
    candidates = (
        ship.get("CurrentJumpRange"),
        ship.get("MaximumJumpRange"),
        ship.get("ReportedMaximumJumpRange"),
        loadout.get("MaxJumpRange"),
    )
    for value in candidates:
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 2)
    return 35.0


def _request_headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT}


def _body_search_headers() -> dict[str, str]:
    # Spansh's web client sends JSON text using this content type.  The live
    # endpoint currently rejects requests.post(..., json=payload) with 400.
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }


def _coordinate_distance(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    values: list[float] = []
    for axis in ("x", "y", "z"):
        left = first.get(axis)
        right = second.get(axis)
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        values.append(float(right) - float(left))
    return math.sqrt(sum(value * value for value in values))


def _distance_from_sol(coordinates: dict[str, Any]) -> float | None:
    return _coordinate_distance({"x": 0.0, "y": 0.0, "z": 0.0}, coordinates)


def _confidence_tier(distance_from_sol: float | None) -> str:
    if distance_from_sol is None:
        return "unknown"
    if distance_from_sol >= HIGH_CONFIDENCE_DISTANCE_FROM_SOL_LY:
        return "high"
    if distance_from_sol >= MEDIUM_CONFIDENCE_DISTANCE_FROM_SOL_LY:
        return "medium"
    return "low"


def _outward_search_center(
    source_coords: dict[str, float] | None,
    radius: int,
) -> tuple[dict[str, float] | None, bool]:
    """Move the query outward when the commander is still near civilization.

    Searching a sphere centred on the current position at ~1,800 ly returns a
    large number of stale records that other commanders have already visited.
    If the current direction from Sol is known, continue on that same radial
    line and centre the search far enough out that the near edge of the normal
    500 ly search is at about 3,000 ly from Sol.
    """
    if source_coords is None:
        return None, False
    source_distance = _distance_from_sol(source_coords)
    if source_distance is None or source_distance < 1.0:
        return dict(source_coords), False
    if source_distance >= HIGH_CONFIDENCE_DISTANCE_FROM_SOL_LY:
        return dict(source_coords), False

    target_distance = HIGH_CONFIDENCE_DISTANCE_FROM_SOL_LY + min(float(radius), 500.0)
    scale = target_distance / source_distance
    return {
        axis: float(source_coords[axis]) * scale
        for axis in ("x", "y", "z")
    }, True


def _supercruise_seconds(distance_to_arrival: float) -> float:
    # A monotonic approximation used only for ranking. It strongly rejects
    # Hutton-like targets while preserving the advantage of close bodies.
    return 35.0 + 0.75 * math.sqrt(max(0.0, distance_to_arrival))


def _direct_jump_estimate(source: dict[str, Any], destination: dict[str, Any], jump_range: float) -> int:
    coordinates = []
    for key in ("x", "y", "z"):
        start = source.get(key)
        end = destination.get(key)
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            return 1
        coordinates.append(float(end) - float(start))
    distance = math.sqrt(sum(component * component for component in coordinates))
    return max(1, math.ceil((distance / max(jump_range, 1.0)) * 1.1))


def _target_score(value: int, jumps: int, arrival_ls: float, species_count: int) -> tuple[float, int]:
    travel_seconds = jumps * 50.0 + _supercruise_seconds(arrival_ls)
    sampling_seconds = 150.0 + max(1, species_count) * 180.0
    total_seconds = max(60, round(travel_seconds + sampling_seconds))
    return value / total_seconds * 3600.0, total_seconds


def _compact_landmarks(landmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "species": landmark.get("subtype") or landmark.get("type"),
            "value": int(landmark.get("value") or 0),
        }
        for landmark in landmarks
        if landmark.get("subtype") or landmark.get("type")
    ]


def _route_targets(result: list[dict[str, Any]], jump_range: float) -> list[dict[str, Any]]:
    if not result:
        return []
    source = result[0]
    targets: list[dict[str, Any]] = []
    for system in result[1:]:
        jumps = _direct_jump_estimate(source, system, jump_range)
        for body in system.get("bodies") or []:
            landmarks = _compact_landmarks(body.get("landmarks") or [])
            priority_value = sum(item["value"] for item in landmarks)
            total_value = int(body.get("landmark_value") or priority_value)
            arrival_ls = float(body.get("distance_to_arrival") or 0)
            scan_value = priority_value or total_value
            credits_per_hour, estimated_seconds = _target_score(
                scan_value, jumps, arrival_ls, len(landmarks)
            )
            targets.append({
                "system": system.get("name"),
                "body": body.get("name"),
                "distance_ly": round(math.dist(
                    [float(source.get(axis) or 0) for axis in ("x", "y", "z")],
                    [float(system.get(axis) or 0) for axis in ("x", "y", "z")],
                ), 2),
                "estimated_jumps": jumps,
                "distance_to_arrival_ls": round(arrival_ls, 1),
                "confirmed_total_value": total_value,
                "priority_scan_value": scan_value,
                "priority_species": landmarks,
                "estimated_target_seconds": estimated_seconds,
                "estimated_credits_per_hour": round(credits_per_hour),
                "first_discovery_bonus_expected": False,
                "strategy": "confirmed_throughput",
            })
    return sorted(
        targets,
        key=lambda item: (-item["estimated_credits_per_hour"], -item["confirmed_total_value"], item["distance_ly"]),
    )


def _poll_route(
    job_id: str,
    *,
    request_get: Callable[..., Any],
    sleep: Callable[[float], None],
    timeout_seconds: float = 20.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = request_get(
            SPANSH_RESULTS_URL.format(job_id=job_id), headers=_request_headers(), timeout=15
        )
        response.raise_for_status()
        payload = response.json()
        state = payload.get("state")
        if state == "failed":
            raise RuntimeError(payload.get("error") or "Spansh exobiology route failed.")
        if state == "completed" or payload.get("result"):
            return payload.get("result") or []
        sleep(0.5)
    raise TimeoutError("Spansh exobiology route did not finish within 20 seconds.")


def plan_confirmed_throughput(
    source_system: str,
    jump_range: float,
    *,
    radius: int,
    max_results: int,
    request_post: Callable[..., Any] = requests.post,
    request_get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    response = request_post(
        SPANSH_EXOBIOLOGY_ROUTE_URL,
        data={
            "from": source_system,
            "range": str(jump_range),
            "radius": str(radius),
            "max_results": str(max_results),
            "min_value": "16000000",
            "loop": "0",
        },
        headers=_request_headers(),
        timeout=20,
    )
    response.raise_for_status()
    job_id = response.json().get("job")
    if not job_id:
        raise RuntimeError("Spansh did not return an exobiology route job id.")
    targets = _route_targets(
        _poll_route(job_id, request_get=request_get, sleep=sleep), jump_range
    )
    return {
        "strategy": "confirmed_throughput",
        "basis": "Confirmed organisms ranked by estimated credits per hour, including jumps and supercruise distance.",
        "targets": targets[:max_results],
    }


def _first_discovery_request(
    profile: ExobiologyProfile,
    source_system: str | None,
    radius: int,
    size: int,
    *,
    reference_coords: dict[str, float] | None = None,
    max_arrival_ls: int = DEFAULT_MAX_ARRIVAL_LS,
) -> dict[str, Any]:
    """Build the same raw body-search shape used by the Spansh web client."""
    filters = {
        **profile.filters,
        "distance": {"min": 0, "max": radius},
        "distance_to_arrival": {
            "comparison": "<=>",
            "value": [0, max_arrival_ls],
        },
        "updated_at": {
            "comparison": "<=>",
            "value": [SPANSH_DATA_START, PRE_ODYSSEY_CUTOFF],
        },
    }
    request: dict[str, Any] = {
        "filters": filters,
        "sort": [
            {"distance": {"direction": "asc"}},
            {"distance_to_arrival": {"direction": "asc"}},
        ],
        "size": size,
        "page": 0,
    }
    if reference_coords is not None:
        request["reference_coords"] = reference_coords
    elif source_system:
        request["reference_system"] = source_system
    else:
        raise ValueError("A current system name or StarPos coordinates are required for Spansh.")
    return request


def _number(body: dict[str, Any], field: str) -> float | None:
    value = body.get(field)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _has_no_volcanism(body: dict[str, Any]) -> bool:
    value = str(body.get("volcanism_type") or "").strip().casefold()
    # Missing volcanism on these old records is unknown, not evidence of
    # activity.  Keep it as a candidate; DSS/BioInsights is the validation gate.
    return not value or value in {"none", "no volcanism"}


def _parent_star_allows_stratum(body: dict[str, Any]) -> bool:
    parents = body.get("parents")
    if not isinstance(parents, list):
        return True
    known_stars = [
        str(parent.get("subtype") or "").strip().casefold()
        for parent in parents
        if isinstance(parent, dict)
        and str(parent.get("type") or "").casefold() == "star"
        and parent.get("subtype")
    ]
    if not known_stars:
        return True
    # Stratum is excluded around O, B, A, G and neutron stars.  Keep unknown
    # parent data as a lead rather than silently converting missing data into a
    # false negative.
    excluded_prefixes = (
        "o ", "o(", "b ", "b(", "a ", "a(", "g ", "g(", "neutron",
    )
    return not any(star.startswith(excluded_prefixes) for star in known_stars)


def _is_tectonicas_compatible(body: dict[str, Any]) -> bool:
    """Apply the atmosphere-specific Tectonicas envelope to one body record."""
    if str(body.get("subtype") or "").casefold() != "high metal content world":
        return False
    if not _parent_star_allows_stratum(body):
        return False
    atmosphere = str(body.get("atmosphere") or "").strip().casefold()
    gravity = _number(body, "gravity")
    temperature = _number(body, "surface_temperature")
    if gravity is None or temperature is None:
        return False

    def within(gravity_min: float, gravity_max: float, temp_min: float, temp_max: float) -> bool:
        return gravity_min <= gravity <= gravity_max and temp_min <= temperature <= temp_max

    if "carbon dioxide-rich" in atmosphere:
        return within(0.035, 0.61, 165, 260)
    if "carbon dioxide" in atmosphere:
        return within(0.045, 0.61, 165, 430)
    if "sulphur dioxide" in atmosphere:
        return within(0.29, 0.62, 165, 450)
    if "ammonia" in atmosphere:
        return within(0.045, 0.38, 165, 177)
    if "oxygen" in atmosphere:
        return within(0.40, 0.52, 165, 246)
    if "argon" in atmosphere:
        return within(0.485, 0.54, 167, 199) and _has_no_volcanism(body)
    if "water" in atmosphere:
        return 0.045 <= gravity <= 0.063 and temperature >= 165 and _has_no_volcanism(body)
    return False


def _system_coordinates(body: dict[str, Any]) -> dict[str, float] | None:
    coordinates: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        value = body.get(f"system_{axis}")
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        coordinates[axis] = float(value)
    return coordinates


def _confidence_explanation(tier: str) -> str:
    if tier == "high":
        return "pre-Odyssey record at least 3000 ly from Sol; better lead, still not a guarantee"
    if tier == "medium":
        return "pre-Odyssey record 2000-2999 ly from Sol; elevated prior-visit risk"
    if tier == "low":
        return "under 2000 ly from Sol; heavy traffic makes stale-record false positives common"
    return "distance from Sol unavailable; First Footfall and First Logged remain unverified"


def _group_stratum_targets(
    bodies: list[dict[str, Any]],
    *,
    source_coords: dict[str, float] | None,
    jump_range: float,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for body in bodies:
        if not _is_tectonicas_compatible(body):
            continue
        system_name = str(body.get("system_name") or "").strip()
        body_name = str(body.get("name") or "").strip()
        if not system_name or not body_name:
            continue
        coordinates = _system_coordinates(body)
        group = groups.setdefault(system_name, {
            "system": system_name,
            "coordinates": coordinates,
            "search_distance_ly": float(body.get("distance") or 0),
            "bodies": [],
        })
        if group["coordinates"] is None and coordinates is not None:
            group["coordinates"] = coordinates
        group["bodies"].append({
            "body": body_name,
            "body_id": body.get("body_id"),
            "distance_to_arrival_ls": round(float(body.get("distance_to_arrival") or 0), 1),
            "atmosphere": body.get("atmosphere"),
            "gravity_g": round(float(body["gravity"]), 4),
            "surface_temperature_k": round(float(body["surface_temperature"]), 1),
            "updated_at": body.get("updated_at"),
        })

    targets: list[dict[str, Any]] = []
    for group in groups.values():
        candidate_bodies = sorted(
            group["bodies"],
            key=lambda item: (item["distance_to_arrival_ls"], item["body"]),
        )
        coordinates = group["coordinates"]
        distance_ly = (
            _coordinate_distance(source_coords, coordinates)
            if source_coords is not None and coordinates is not None
            else group["search_distance_ly"]
        )
        distance_ly = float(distance_ly or 0)
        jumps = max(1, math.ceil((distance_ly / max(jump_range, 1.0)) * 1.1))
        distance_from_sol = _distance_from_sol(coordinates) if coordinates is not None else None
        confidence = _confidence_tier(distance_from_sol)
        potential_value = TECTONICAS_FIRST_LOGGED_VALUE * len(candidate_bodies)
        travel_seconds = jumps * 50.0
        body_seconds = sum(
            375.0 + _supercruise_seconds(body["distance_to_arrival_ls"])
            for body in candidate_bodies
        )
        estimated_seconds = max(60, round(travel_seconds + body_seconds))
        potential_per_hour = round(potential_value / estimated_seconds * 3600)
        targets.append({
            "system": group["system"],
            "body": candidate_bodies[0]["body"],
            "bodies": candidate_bodies,
            "candidate_body_count": len(candidate_bodies),
            "coordinates": coordinates,
            "distance_ly": round(distance_ly, 2),
            "distance_from_sol_ly": (
                round(distance_from_sol, 2) if distance_from_sol is not None else None
            ),
            "estimated_jumps": jumps,
            "potential_first_logged_ceiling": potential_value,
            "potential_credits_per_hour_ceiling": potential_per_hour,
            "estimated_system_seconds": estimated_seconds,
            "first_discovery_bonus_expected": "heuristic_not_guaranteed",
            "confidence_tier": confidence,
            "confidence": _confidence_explanation(confidence),
            "strategy": "stratum_sniping",
            "targeted_fss_instruction": (
                "Honk, resolve only these listed HMC bodies in FSS, and stop: "
                + ", ".join(body["body"] for body in candidate_bodies)
                + ". Do not complete the full-system FSS. Check BioInsights after each body; DSS only a Stratum candidate."
            ),
        })

    confidence_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    remaining = sorted(
        targets,
        key=lambda item: (
            -confidence_rank[item["confidence_tier"]],
            -item["candidate_body_count"],
            -item["potential_credits_per_hour_ceiling"],
            item["distance_ly"],
        ),
    )
    if not remaining:
        return []

    # Start with the best high-confidence cluster, then greedily minimize legs
    # within the best confidence tier still available.
    ordered = [remaining.pop(0)]
    while remaining:
        best_tier = max(confidence_rank[item["confidence_tier"]] for item in remaining)
        eligible = [
            item for item in remaining
            if confidence_rank[item["confidence_tier"]] == best_tier
        ]
        previous_coords = ordered[-1]["coordinates"]

        def leg_key(item: dict[str, Any]) -> tuple[float, float, int]:
            leg = (
                _coordinate_distance(previous_coords, item["coordinates"])
                if previous_coords is not None and item["coordinates"] is not None
                else item["distance_ly"]
            )
            return (
                float(leg or 0) / max(1, item["candidate_body_count"]),
                -float(item["potential_credits_per_hour_ceiling"]),
                -int(item["candidate_body_count"]),
            )

        next_target = min(eligible, key=leg_key)
        remaining.remove(next_target)
        ordered.append(next_target)

    previous_coords = source_coords
    for index, target in enumerate(ordered, start=1):
        leg_distance = (
            _coordinate_distance(previous_coords, target["coordinates"])
            if previous_coords is not None and target["coordinates"] is not None
            else target["distance_ly"]
        )
        target["route_order"] = index
        target["route_leg_distance_ly"] = round(float(leg_distance or 0), 2)
        if target["coordinates"] is not None:
            previous_coords = target["coordinates"]
    return ordered


def plan_first_discovery(
    source_system: str | None,
    jump_range: float,
    *,
    radius: int,
    max_results: int,
    source_coords: dict[str, float] | None = None,
    reference_coords: dict[str, float] | None = None,
    max_arrival_ls: int = DEFAULT_MAX_ARRIVAL_LS,
    request_post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    profile = FIRST_DISCOVERY_PROFILES[0]
    request = _first_discovery_request(
        profile,
        source_system,
        radius,
        100,
        reference_coords=reference_coords,
        max_arrival_ls=max_arrival_ls,
    )
    response = request_post(
        SPANSH_BODIES_URL,
        data=json.dumps(request, separators=(",", ":")),
        headers=_body_search_headers(),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    raw_bodies = payload.get("results") or []
    bounded_bodies = [
        body for body in raw_bodies
        if (_number(body, "distance_to_arrival") is not None)
        and 0 <= float(body["distance_to_arrival"]) <= max_arrival_ls
    ]
    targets = _group_stratum_targets(
        bounded_bodies,
        source_coords=source_coords,
        jump_range=jump_range,
    )
    return {
        "strategy": "stratum_sniping",
        "basis": (
            "Exact HMC body records last updated before Odyssey, post-filtered against Tectonicas conditions. "
            "This is a stale-record heuristic, not proof of First Footfall or First Logged."
        ),
        "candidate_records_returned": len(raw_bodies),
        "compatible_candidate_bodies": sum(item["candidate_body_count"] for item in targets),
        "targets": targets[:max_results],
    }


def plan_exobiology(
    obj: dict[str, Any],
    projected_states: Any,
    *,
    request_post: Callable[..., Any] = requests.post,
    request_get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    location = get_state_dict(projected_states, "Location")
    source_system_value = str(location.get("StarSystem") or "").strip()
    source_system = (
        source_system_value
        if source_system_value and source_system_value.casefold() != "unknown"
        else None
    )
    source_coords = current_coordinates(projected_states)
    if source_system is None and source_coords is None:
        raise ValueError("Current location is unknown; wait for a Location or FSDJump journal event.")
    jump_range = current_jump_range(projected_states)
    requested_strategy = str(obj.get("strategy") or "auto").casefold()
    strategy = (
        "confirmed_throughput"
        if requested_strategy in ("throughput", "confirmed_throughput")
        else "stratum_sniping"
    )
    radius = max(25, min(5000, int(
        obj.get("radius")
        or (50 if strategy == "confirmed_throughput" else DEFAULT_STRATUM_RADIUS_LY)
    )))
    max_results = max(1, min(20, int(obj.get("max_results") or 8)))
    max_arrival_ls = max(100, min(100_000, int(
        obj.get("max_arrival_ls") or DEFAULT_MAX_ARRIVAL_LS
    )))

    if strategy == "confirmed_throughput":
        if source_system is None:
            raise ValueError(
                "The deterministic Exomastery route needs a Spansh system name; "
                "use auto/first_discovery with live StarPos coordinates until the next named system."
            )
        plan = plan_confirmed_throughput(
            source_system,
            jump_range,
            radius=radius,
            max_results=max_results,
            request_post=request_post,
            request_get=request_get,
            sleep=sleep,
        )
        search_center = source_coords
        outward_staging = False
    else:
        search_center, outward_staging = _outward_search_center(source_coords, radius)
        plan = plan_first_discovery(
            source_system,
            jump_range,
            radius=radius,
            max_results=max_results,
            source_coords=source_coords,
            reference_coords=search_center,
            max_arrival_ls=max_arrival_ls,
            request_post=request_post,
        )

    targets = plan["targets"]
    if targets and strategy == "stratum_sniping":
        navigation_instruction = {"system": targets[0]["system"]}
    elif targets:
        navigation_instruction = {
            "system": targets[0]["system"],
            "body": targets[0]["body"],
        }
    else:
        navigation_instruction = None
    if strategy == "stratum_sniping":
        operational_notes = [
            (
                "Do not FSS the whole system. Honk, resolve only the listed HMC candidate body or bodies, "
                "read BioInsights, then stop."
            ),
            "DSS only a candidate that BioInsights predicts can contain Stratum; confirm the Stratum DSS filter before landing.",
            "The pre-Odyssey timestamp is a traffic heuristic, never a guarantee of First Footfall or the 5x First Logged payout.",
        ]
    else:
        operational_notes = [
            "Navigate to the listed known body; a full-system FSS is not required for this throughput route.",
            "These organisms are already public records, so rank them by reliable base-value throughput rather than a First Logged bonus.",
        ]
    operational_notes.extend([
        "Complete all three samples of one species before starting another.",
        "Prioritize the listed high-value species; skip low-value organisms when they reduce credits per hour.",
        "Unsold biodata is lost on death.",
    ])
    plan.update({
        "source_system": source_system or "Unknown",
        "source_coords": source_coords,
        "jump_range": jump_range,
        "radius_ly": radius,
        "max_arrival_ls": max_arrival_ls,
        "search_center_coords": search_center,
        "outward_staging_applied": outward_staging,
        "recommended_target": targets[0] if targets else None,
        "navigation_instruction": navigation_instruction,
        "targeted_fss_bodies": (
            [body["body"] for body in targets[0]["bodies"]]
            if targets and strategy == "stratum_sniping" else []
        ),
        "operational_notes": operational_notes,
    })
    return plan
