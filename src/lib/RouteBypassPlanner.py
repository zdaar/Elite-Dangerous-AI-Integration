from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import requests

from .RouteSafety import RouteSafetyPolicy
from .RouteSafetyProvider import assess_spansh_systems
from .RouteSafetySupervisor import RouteHop


EDSM_SPHERE_SYSTEMS_URL = "https://www.edsm.net/api-v1/sphere-systems"
USER_AGENT = "COVAS-NEXT/route-safety-bypass"


@dataclass(frozen=True)
class BypassCandidate:
    hop: RouteHop
    jump_distance_ly: float
    distance_to_destination_ly: float
    clearance_from_dangerous_system_ly: float
    lateral_offset_ly: float
    primary_star_type: str
    safety_status: str
    safety_warning: str | None = None


def _coords(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, dict):
        return None
    coordinates = tuple(value.get(axis) for axis in ("x", "y", "z"))
    if not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in coordinates):
        return None
    return tuple(float(item) for item in coordinates)


def _distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return math.dist(first, second)


def _lateral_offset(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    line = tuple(end[index] - start[index] for index in range(3))
    length_squared = sum(value * value for value in line)
    if length_squared <= 0:
        return _distance(point, start)
    projection = sum(
        (point[index] - start[index]) * line[index]
        for index in range(3)
    ) / length_squared
    nearest = tuple(start[index] + projection * line[index] for index in range(3))
    return _distance(point, nearest)


def find_verified_safe_bypass(
    boundary: RouteHop,
    dangerous: RouteHop,
    destination: RouteHop,
    jump_range_ly: float,
    forbidden_system_ids: set[int],
    policy: RouteSafetyPolicy,
    *,
    request_get: Callable[..., Any] = requests.get,
    request_post: Callable[..., Any] = requests.post,
) -> tuple[BypassCandidate | None, str | None]:
    """Choose a known-safe, scoopable, single-jump lateral waypoint."""
    if boundary.coordinates is None or dangerous.coordinates is None or destination.coordinates is None:
        return None, "Route coordinates are incomplete."
    if jump_range_ly <= 0:
        return None, "Current jump range is unavailable."

    radius = max(5, min(100, int(math.floor(jump_range_ly * 0.98))))
    try:
        response = request_get(
            EDSM_SPHERE_SYSTEMS_URL,
            params={
                "systemName": boundary.name,
                "radius": radius,
                "showCoordinates": 1,
                "showId": 1,
                "showPrimaryStar": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            raise ValueError("EDSM returned malformed nearby-system results.")
    except Exception as error:
        return None, f"Nearby-system provider unavailable: {error}"

    geometric: list[tuple[float, dict[str, Any], RouteHop, float, float, float, str]] = []
    original_remaining = _distance(boundary.coordinates, destination.coordinates)
    excluded = set(forbidden_system_ids)
    for known in (boundary, dangerous, destination):
        if known.system_address is not None:
            excluded.add(known.system_address)
    for record in records:
        if not isinstance(record, dict) or record.get("coordsLocked") is False:
            continue
        system_id = record.get("id64")
        if not isinstance(system_id, int) or system_id in excluded:
            continue
        primary_star = record.get("primaryStar")
        if not isinstance(primary_star, dict) or primary_star.get("isScoopable") is not True:
            continue
        candidate_coords = _coords(record.get("coords"))
        name = str(record.get("name") or "").strip()
        if candidate_coords is None or not name:
            continue
        jump_distance = _distance(boundary.coordinates, candidate_coords)
        if not (1.0 <= jump_distance <= jump_range_ly * 0.98):
            continue
        destination_distance = _distance(candidate_coords, destination.coordinates)
        danger_clearance = _distance(candidate_coords, dangerous.coordinates)
        lateral = _lateral_offset(
            candidate_coords,
            boundary.coordinates,
            destination.coordinates,
        )
        progress = original_remaining - destination_distance
        # Prefer useful forward progress and a lateral displacement that makes
        # Elite less likely to select the same forbidden hop on the replot.
        score = progress + 0.55 * lateral + 0.30 * danger_clearance - 0.05 * jump_distance
        star_type = str(primary_star.get("type") or "Unknown")
        hop = RouteHop(name, system_id, candidate_coords)
        geometric.append((
            score,
            record,
            hop,
            jump_distance,
            destination_distance,
            danger_clearance,
            star_type,
        ))

    geometric.sort(key=lambda item: (-item[0], item[2].name.casefold()))
    shortlist = geometric[:20]
    if not shortlist:
        return None, "No scoopable one-jump waypoint with locked coordinates was found."
    assessments, error = assess_spansh_systems(
        {item[2].system_address: item[2].name for item in shortlist if item[2].system_address is not None},
        policy,
        request_post=request_post,
    )
    unknown_fallback = None
    for _score, _record, hop, jump_distance, destination_distance, danger_clearance, star_type in shortlist:
        if hop.system_address is None:
            continue
        assessment = assessments.get(hop.system_address)
        status = assessment.status if assessment is not None else "unknown"
        candidate = BypassCandidate(
            hop=hop,
            jump_distance_ly=round(jump_distance, 2),
            distance_to_destination_ly=round(destination_distance, 2),
            clearance_from_dangerous_system_ly=round(danger_clearance, 2),
            lateral_offset_ly=round(
                _lateral_offset(hop.coordinates, boundary.coordinates, destination.coordinates),
                2,
            ),
            primary_star_type=star_type,
            safety_status=status,
            safety_warning=(
                assessment.reason if assessment is not None
                else error or "No close-star geometry was returned."
            ) if status == "unknown" else None,
        )
        if status == "unknown" and unknown_fallback is None:
            unknown_fallback = candidate
        if status != "safe":
            continue
        return candidate, None
    if unknown_fallback is not None:
        return unknown_fallback, (
            "No positively safe nearby waypoint was available; using a scoopable waypoint with unknown companion geometry."
        )
    return None, error or "Nearby candidates exist, but none has usable star geometry."
