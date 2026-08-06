from __future__ import annotations

import json
import threading
from typing import Any, Callable

import requests

from .RouteSafety import (
    ROUTE_SAFETY_CACHE,
    RouteSafetyPolicy,
    SystemSafetyAssessment,
    assess_star_system,
    star_geometry_from_spansh,
)


SPANSH_BODIES_URL = "https://spansh.co.uk/api/bodies/search"
USER_AGENT = "COVAS-NEXT/route-safety"
SYSTEMS_PER_REQUEST = 25


def _system_id64(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }


def _request(system_ids: list[int]) -> dict[str, Any]:
    return {
        "filters": {
            "system_id64": {"value": [str(system_id) for system_id in system_ids]},
            "type": {"value": ["Star"]},
        },
        "sort": [{"system_id64": {"direction": "asc"}}],
        "size": 100,
        "page": 0,
    }


def assess_spansh_systems(
    systems: dict[int, str],
    policy: RouteSafetyPolicy,
    *,
    request_post: Callable[..., Any] = requests.post,
) -> tuple[dict[int, SystemSafetyAssessment], str | None]:
    """Acquire exact records in bounded batches, then classify them locally."""
    systems = {
        system_id: name
        for raw_id, name in systems.items()
        if (system_id := _system_id64(raw_id)) is not None
    }
    if not systems:
        return {}, None
    assessments: dict[int, SystemSafetyAssessment] = {}
    system_items = list(systems.items())
    for offset in range(0, len(system_items), SYSTEMS_PER_REQUEST):
        batch = dict(system_items[offset:offset + SYSTEMS_PER_REQUEST])
        try:
            response = request_post(
                SPANSH_BODIES_URL,
                data=json.dumps(_request(list(batch)), separators=(",", ":")),
                headers=_headers(),
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            records = payload.get("results") or []
            if not isinstance(records, list):
                raise ValueError("Spansh returned malformed star geometry results.")
        except Exception as error:
            return assessments, f"Star geometry provider unavailable: {error}"

        stars_by_id: dict[int, list[Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            system_id = _system_id64(record.get("system_id64"))
            star = star_geometry_from_spansh(record)
            if system_id in batch and star is not None:
                stars_by_id.setdefault(system_id, []).append(star)

        batch_assessments = {
            system_id: assess_star_system(
                name,
                stars_by_id.get(system_id, []),
                policy,
                system_id64=system_id,
            )
            for system_id, name in batch.items()
        }
        total = payload.get("count")
        if isinstance(total, int) and total > len(records):
            for system_id, assessment in list(batch_assessments.items()):
                if assessment.status != "dangerous":
                    batch_assessments[system_id] = SystemSafetyAssessment(
                        assessment.system,
                        system_id,
                        "unknown",
                        "The exact star query was truncated, so a complete safe envelope cannot be proven.",
                        {"returned_records": len(records), "matching_records": total},
                    )
        assessments.update(batch_assessments)

    for assessment in assessments.values():
        ROUTE_SAFETY_CACHE.put(assessment, policy)
    return assessments, None


def prefetch_spansh_systems_nonblocking(
    systems: dict[int, str],
    policy: RouteSafetyPolicy,
    *,
    request_post: Callable[..., Any] = requests.post,
    on_complete: Callable[[dict[int, SystemSafetyAssessment], str | None], None] | None = None,
) -> None:
    """Populate the charge-time cache without blocking journal processing."""
    missing = {
        system_id: name
        for system_id, name in systems.items()
        if ROUTE_SAFETY_CACHE.get(system_id, policy) is None
    }
    if not missing:
        if on_complete is not None:
            cached = {
                system_id: assessment
                for system_id in systems
                if (assessment := ROUTE_SAFETY_CACHE.get(system_id, policy)) is not None
            }
            threading.Thread(
                target=on_complete,
                args=(cached, None),
                name="route-safety-cached-callback",
                daemon=True,
            ).start()
        return


    def run() -> None:
        assessments, error = assess_spansh_systems(
            missing,
            policy,
            request_post=request_post,
        )
        if on_complete is not None:
            on_complete(assessments, error)

    thread = threading.Thread(
        target=run,
        name="route-safety-prefetch",
        daemon=True,
    )
    thread.start()
