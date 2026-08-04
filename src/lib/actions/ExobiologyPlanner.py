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


@dataclass(frozen=True)
class ExobiologyProfile:
    name: str
    expected_base_value: int
    filters: dict[str, Any]


FIRST_DISCOVERY_PROFILES = (
    ExobiologyProfile(
        name="rocky_co2_stack",
        expected_base_value=90_323_900,
        filters={
            "is_landable": {"value": True},
            "subtype": {"value": ["Rocky body"]},
            "atmosphere": {"value": ["Thin Carbon dioxide"]},
            "gravity": {"comparison": "<=>", "value": [0.04, 0.07]},
            "surface_temperature": {"comparison": "<=>", "value": [190, 196]},
            "genuses": {
                "value": ["Stratum", "Clypeus", "Aleoids", "Osseus", "Tussocks"],
                "logic": "and",
            },
            "signals": [{"comparison": "<=>", "name": "Biological", "count": [8, 20]}],
        },
    ),
    ExobiologyProfile(
        name="hmc_water_stack",
        expected_base_value=85_819_600,
        filters={
            "is_landable": {"value": True},
            "subtype": {"value": ["High metal content world"]},
            "atmosphere": {"value": ["Thin Water", "Water"]},
            "gravity": {"comparison": "<=>", "value": [0.04, 0.065]},
            "volcanism_type": {"value": ["No volcanism"]},
            "genuses": {"value": ["Stratum", "Cactoids", "Tussocks"], "logic": "and"},
            "signals": [{"comparison": "<=>", "name": "Biological", "count": [7, 20]}],
        },
    ),
    ExobiologyProfile(
        name="tectonicas_volume",
        expected_base_value=19_010_800,
        filters={
            "is_landable": {"value": True},
            "subtype": {"value": ["High metal content world"]},
            "atmosphere": {"value": ["Thin Carbon dioxide", "Thin Sulphur dioxide"]},
            "gravity": {"comparison": "<=>", "value": [0.0, 0.62]},
            "surface_temperature": {"comparison": "<=>", "value": [165, 450]},
            "genuses": {"value": ["Stratum"]},
            "signals": [{"comparison": "<=>", "name": "Biological", "count": [1, 20]}],
        },
    ),
)


def current_system(projected_states: Any) -> str:
    location = get_state_dict(projected_states, "Location")
    system = str(location.get("StarSystem") or "").strip()
    if not system or system.casefold() == "unknown":
        raise ValueError("Current system is unknown; wait for a Location or FSDJump journal event.")
    return system


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


def _first_discovery_request(profile: ExobiologyProfile, source_system: str, radius: int, size: int) -> dict[str, Any]:
    filters = {
        **profile.filters,
        "distance": {"min": 0, "max": radius},
        # Predicted genera with no recorded landmark value are actionable
        # unconfirmed candidates. An updated_at cutoff was intentionally not
        # used: live validation found it returns no usable targets near the
        # Bubble and does not represent first-logged state reliably.
        "landmark_value": {"comparison": "<=>", "value": [0, 0]},
    }
    return {
        "filters": filters,
        "sort": [
            {"distance": {"direction": "asc"}},
            {"distance_to_arrival": {"direction": "asc"}},
        ],
        "size": size,
        "page": 0,
        "reference_system": source_system,
    }


def plan_first_discovery(
    source_system: str,
    jump_range: float,
    *,
    radius: int,
    max_results: int,
    request_post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    per_profile = max(3, min(10, max_results))
    for profile in FIRST_DISCOVERY_PROFILES:
        response = request_post(
            SPANSH_BODIES_URL,
            json=_first_discovery_request(profile, source_system, radius, per_profile),
            headers=_request_headers(),
            timeout=30,
        )
        response.raise_for_status()
        for body in response.json().get("results") or []:
            distance_ly = float(body.get("distance") or 0)
            jumps = max(1, math.ceil((distance_ly / max(jump_range, 1.0)) * 1.1))
            arrival_ls = float(body.get("distance_to_arrival") or 0)
            signal_count = int(body.get("signal_count") or len(body.get("genuses") or []) or 1)
            estimated_base = profile.expected_base_value
            expected_first_logged = estimated_base * 5
            credits_per_hour, estimated_seconds = _target_score(
                expected_first_logged, jumps, arrival_ls, signal_count
            )
            targets.append({
                "system": body.get("system_name"),
                "body": body.get("name"),
                "profile": profile.name,
                "distance_ly": round(distance_ly, 2),
                "estimated_jumps": jumps,
                "distance_to_arrival_ls": round(arrival_ls, 1),
                "predicted_genuses": body.get("genuses") or [],
                "biological_signals": signal_count,
                "estimated_base_ceiling": estimated_base,
                "estimated_first_logged_ceiling": expected_first_logged,
                "estimated_target_seconds": estimated_seconds,
                "estimated_credits_per_hour": round(credits_per_hour),
                "first_discovery_bonus_expected": "possible_not_guaranteed",
                "strategy": "first_discovery",
                "confidence": "unconfirmed profile prediction; landmark_value=0 is not proof that the 5x bonus remains available",
            })
    targets.sort(
        key=lambda item: (-item["estimated_credits_per_hour"], -item["estimated_first_logged_ceiling"], item["distance_ly"])
    )
    return {
        "strategy": "first_discovery",
        "basis": "Predicted genera with no recorded organism value; payout can reach 5x base if still first logged, but the bonus is not guaranteed by Spansh.",
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
    source_system = current_system(projected_states)
    jump_range = current_jump_range(projected_states)
    requested_strategy = str(obj.get("strategy") or "auto").casefold()
    strategy = "confirmed_throughput" if requested_strategy in ("auto", "throughput", "confirmed_throughput") else "first_discovery"
    radius = max(25, min(5000, int(obj.get("radius") or (50 if strategy == "confirmed_throughput" else 2000))))
    max_results = max(1, min(20, int(obj.get("max_results") or 8)))

    if strategy == "confirmed_throughput":
        plan = plan_confirmed_throughput(
            source_system,
            jump_range,
            radius=radius,
            max_results=max_results,
            request_post=request_post,
            request_get=request_get,
            sleep=sleep,
        )
    else:
        plan = plan_first_discovery(
            source_system,
            jump_range,
            radius=radius,
            max_results=max_results,
            request_post=request_post,
        )

    targets = plan["targets"]
    plan.update({
        "source_system": source_system,
        "jump_range": jump_range,
        "radius_ly": radius,
        "recommended_target": targets[0] if targets else None,
        "navigation_instruction": (
            {"system": targets[0]["system"], "body": targets[0]["body"]}
            if targets else None
        ),
        "operational_notes": [
            "Complete all three samples of one species before starting another.",
            "Prioritize the listed high-value species; skip low-value organisms when they reduce credits per hour.",
            "Unsold biodata is lost on death.",
        ],
    })
    return plan
