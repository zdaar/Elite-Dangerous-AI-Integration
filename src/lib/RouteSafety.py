from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Sequence


SafetyStatus = Literal["safe", "dangerous", "unknown"]
UnknownSystemPolicy = Literal["allow", "exclude"]

LIGHT_SECONDS_PER_AU = 499.004783836
LIGHT_SECONDS_PER_METRE = 1.0 / 299_792_458.0
LIGHT_SECONDS_PER_SOLAR_RADIUS = 2.320605455
DEFAULT_MAX_SURFACE_GAP_RATIO = 1.0


@dataclass(frozen=True)
class RouteSafetyPolicy:
    """Reusable policy for filtering route candidates before navigation.

    ``max_surface_gap_ratio`` is deliberately dimensionless. A value of 1.0
    treats a binary as dangerous when its minimum empty gap is no larger than
    the two stellar radii added together. The rule is a conservative geometry
    gate, not a prediction of a particular ship's heat response.
    """

    enabled: bool = True
    unknown_system_policy: UnknownSystemPolicy = "allow"
    max_surface_gap_ratio: float = DEFAULT_MAX_SURFACE_GAP_RATIO

    def __post_init__(self) -> None:
        if self.unknown_system_policy not in ("allow", "exclude"):
            raise ValueError("unknown_system_policy must be 'allow' or 'exclude'")
        if not math.isfinite(self.max_surface_gap_ratio) or self.max_surface_gap_ratio < 0:
            raise ValueError("max_surface_gap_ratio must be a finite non-negative number")


@dataclass(frozen=True)
class StarGeometry:
    name: str
    subtype: str | None
    is_arrival_star: bool | None
    distance_from_arrival_ls: float | None
    solar_radius: float | None
    semi_major_axis_ls: float | None
    orbital_eccentricity: float | None
    orbital_period_days: float | None
    immediate_parent: str | None

    @property
    def radius_ls(self) -> float | None:
        if self.solar_radius is None:
            return None
        return self.solar_radius * LIGHT_SECONDS_PER_SOLAR_RADIUS


@dataclass(frozen=True)
class SystemSafetyAssessment:
    system: str
    system_id64: int | None
    status: SafetyStatus
    reason: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "system_id64": self.system_id64,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class RouteCandidateFilterResult:
    included: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    unknown_allowed: list[dict[str, Any]]


class RouteSafetyAssessmentCache:
    """Thread-safe cache shared by planners and the live jump guard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._assessments: dict[tuple[int, float], SystemSafetyAssessment] = {}

    @staticmethod
    def _key(system_id64: int, policy: RouteSafetyPolicy) -> tuple[int, float]:
        return system_id64, round(policy.max_surface_gap_ratio, 6)

    def put(
        self,
        assessment: SystemSafetyAssessment,
        policy: RouteSafetyPolicy,
    ) -> None:
        if assessment.system_id64 is None:
            return
        with self._lock:
            self._assessments[self._key(assessment.system_id64, policy)] = assessment

    def get(
        self,
        system_id64: int,
        policy: RouteSafetyPolicy,
    ) -> SystemSafetyAssessment | None:
        with self._lock:
            return self._assessments.get(self._key(system_id64, policy))


ROUTE_SAFETY_CACHE = RouteSafetyAssessmentCache()


def route_safety_policy_from_config(config: dict[str, Any]) -> RouteSafetyPolicy:
    unknown_policy = config.get("route_safety_unknown_system_policy", "allow")
    if unknown_policy not in ("allow", "exclude"):
        unknown_policy = "allow"
    raw_ratio = config.get(
        "route_safety_max_surface_gap_ratio",
        DEFAULT_MAX_SURFACE_GAP_RATIO,
    )
    ratio = (
        float(raw_ratio)
        if isinstance(raw_ratio, (int, float)) and math.isfinite(float(raw_ratio))
        else DEFAULT_MAX_SURFACE_GAP_RATIO
    )
    return RouteSafetyPolicy(
        enabled=bool(config.get("route_safety_close_star_enabled", True)),
        unknown_system_policy=unknown_policy,
        max_surface_gap_ratio=max(0.0, min(5.0, ratio)),
    )


def _finite_number(value: Any, *, positive: bool = False) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _parent_key(parents: Any) -> str | None:
    if not isinstance(parents, list) or not parents:
        return None
    parent = parents[0]
    if not isinstance(parent, dict):
        return None
    parent_type = parent.get("type")
    parent_id = parent.get("id64")
    if isinstance(parent_type, str) and parent_id is not None:
        return f"{parent_type.casefold()}:{parent_id}"
    if len(parent) == 1:
        key, value = next(iter(parent.items()))
        return f"{str(key).casefold()}:{value}"
    return None


def star_geometry_from_spansh(record: dict[str, Any]) -> StarGeometry | None:
    if str(record.get("type") or "").casefold() != "star":
        return None
    distance = _finite_number(record.get("distance_to_arrival"))
    is_main = record.get("is_main_star")
    is_arrival_star = is_main if isinstance(is_main, bool) else (
        True if distance == 0 else None
    )
    semi_major_axis_au = _finite_number(record.get("semi_major_axis"), positive=True)
    return StarGeometry(
        name=str(record.get("name") or "Unknown star"),
        subtype=str(record.get("subtype") or "").strip() or None,
        is_arrival_star=is_arrival_star,
        distance_from_arrival_ls=distance,
        solar_radius=_finite_number(record.get("solar_radius"), positive=True),
        semi_major_axis_ls=(
            semi_major_axis_au * LIGHT_SECONDS_PER_AU
            if semi_major_axis_au is not None else None
        ),
        orbital_eccentricity=_finite_number(record.get("orbital_eccentricity")),
        orbital_period_days=_finite_number(record.get("orbital_period"), positive=True),
        immediate_parent=_parent_key(record.get("parents")),
    )


def star_geometry_from_edsm(record: dict[str, Any]) -> StarGeometry | None:
    if str(record.get("type") or "").casefold() != "star":
        return None
    distance = _finite_number(record.get("distanceToArrival"))
    is_main = record.get("isMainStar")
    is_arrival_star = is_main if isinstance(is_main, bool) else (
        True if distance == 0 else None
    )
    semi_major_axis_au = _finite_number(record.get("semiMajorAxis"), positive=True)
    return StarGeometry(
        name=str(record.get("name") or "Unknown star"),
        subtype=str(record.get("subType") or "").strip() or None,
        is_arrival_star=is_arrival_star,
        distance_from_arrival_ls=distance,
        solar_radius=_finite_number(record.get("solarRadius"), positive=True),
        semi_major_axis_ls=(
            semi_major_axis_au * LIGHT_SECONDS_PER_AU
            if semi_major_axis_au is not None else None
        ),
        orbital_eccentricity=_finite_number(record.get("orbitalEccentricity")),
        orbital_period_days=_finite_number(record.get("orbitalPeriod"), positive=True),
        immediate_parent=_parent_key(record.get("parents")),
    )


def star_geometry_from_journal(record: dict[str, Any]) -> StarGeometry | None:
    if not record.get("StarType"):
        return None
    distance = _finite_number(record.get("DistanceFromArrivalLS"))
    semi_major_axis_metres = _finite_number(record.get("SemiMajorAxis"), positive=True)
    orbital_period_seconds = _finite_number(record.get("OrbitalPeriod"), positive=True)
    radius_metres = _finite_number(record.get("Radius"), positive=True)
    return StarGeometry(
        name=str(record.get("BodyName") or "Unknown star"),
        subtype=str(record.get("StarType") or "").strip() or None,
        is_arrival_star=True if distance == 0 else None,
        distance_from_arrival_ls=distance,
        solar_radius=(
            radius_metres * LIGHT_SECONDS_PER_METRE / LIGHT_SECONDS_PER_SOLAR_RADIUS
            if radius_metres is not None else None
        ),
        semi_major_axis_ls=(
            semi_major_axis_metres * LIGHT_SECONDS_PER_METRE
            if semi_major_axis_metres is not None else None
        ),
        orbital_eccentricity=_finite_number(record.get("Eccentricity")),
        orbital_period_days=(
            orbital_period_seconds / 86_400.0
            if orbital_period_seconds is not None else None
        ),
        immediate_parent=_parent_key(record.get("Parents")),
    )


def _is_compact_object(star: StarGeometry) -> bool:
    subtype = str(star.subtype or "").casefold()
    return any(marker in subtype for marker in (
        "black hole",
        "neutron",
        "white dwarf",
        "stellar remnant",
    ))


def _minimum_pair_separation_ls(
    arrival_star: StarGeometry,
    companion: StarGeometry,
) -> tuple[float | None, str | None]:
    arrival_axis = arrival_star.semi_major_axis_ls
    companion_axis = companion.semi_major_axis_ls
    same_parent = bool(
        arrival_star.immediate_parent
        and arrival_star.immediate_parent == companion.immediate_parent
    )
    if same_parent and arrival_axis is not None and companion_axis is not None:
        eccentricities = [
            value
            for value in (
                arrival_star.orbital_eccentricity,
                companion.orbital_eccentricity,
            )
            if value is not None and 0 <= value < 1
        ]
        if eccentricities:
            return (
                (arrival_axis + companion_axis) * (1.0 - max(eccentricities)),
                "shared_barycentre_periapsis",
            )

    # A companion orbiting a parent at the system origin can still provide a
    # useful invariant lower bound when the arrival star has no own orbit.
    if arrival_axis is None and companion_axis is not None:
        eccentricity = companion.orbital_eccentricity
        if eccentricity is not None and 0 <= eccentricity < 1:
            return companion_axis * (1.0 - eccentricity), "companion_periapsis"

    observed = companion.distance_from_arrival_ls
    if observed is not None and observed >= 0:
        return observed, "recorded_separation"
    return None, None


def assess_star_system(
    system: str,
    stars: Sequence[StarGeometry],
    policy: RouteSafetyPolicy,
    *,
    system_id64: int | None = None,
) -> SystemSafetyAssessment:
    """Classify one system using only supplied geometry.

    This function is pure: it performs no network, filesystem, LLM, or game
    control operation. Callers are responsible for acquiring and normalizing
    star records before invoking it.
    """

    if not policy.enabled:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "unknown",
            "Close-star route safety is disabled.",
            {"rule": "disabled"},
        )
    if not stars:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "unknown",
            "No intra-system star geometry is available.",
            {"missing": ["star records"]},
        )

    arrival_candidates = [star for star in stars if star.is_arrival_star is True]
    if len(arrival_candidates) != 1:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "unknown",
            "The arrival star cannot be identified unambiguously.",
            {"arrival_star_candidates": [star.name for star in arrival_candidates]},
        )
    arrival_star = arrival_candidates[0]
    companions = [star for star in stars if star is not arrival_star]
    if not companions:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "safe",
            "Only one catalogued star is present; there is no known close-star pair.",
            {"arrival_star": arrival_star.name, "catalogued_star_count": 1},
        )

    arrival_radius = arrival_star.radius_ls
    if arrival_radius is None:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "unknown",
            "The arrival star radius is missing or malformed.",
            {"arrival_star": arrival_star.name, "missing": ["solar_radius"]},
        )

    unknown_pairs: list[dict[str, Any]] = []
    safe_pairs: list[dict[str, Any]] = []
    for companion in companions:
        if _is_compact_object(arrival_star) or _is_compact_object(companion):
            unknown_pairs.append({
                "arrival_star": arrival_star.name,
                "companion": companion.name,
                "reason": "Compact-object exclusion zones are not represented by photospheric radius.",
            })
            continue
        companion_radius = companion.radius_ls
        if companion_radius is None:
            unknown_pairs.append({
                "arrival_star": arrival_star.name,
                "companion": companion.name,
                "reason": "Companion radius is missing or malformed.",
            })
            continue

        separation, separation_basis = _minimum_pair_separation_ls(
            arrival_star,
            companion,
        )
        if separation is None or separation_basis is None:
            unknown_pairs.append({
                "arrival_star": arrival_star.name,
                "companion": companion.name,
                "reason": "No separation or complete orbital envelope is available.",
            })
            continue

        combined_radius = arrival_radius + companion_radius
        threshold = combined_radius * (1.0 + policy.max_surface_gap_ratio)
        surface_gap = separation - combined_radius
        evidence = {
            "arrival_star": arrival_star.name,
            "companion": companion.name,
            "separation_basis": separation_basis,
            "minimum_or_recorded_center_separation_ls": round(separation, 6),
            "combined_stellar_radius_ls": round(combined_radius, 6),
            "surface_gap_ls": round(surface_gap, 6),
            "maximum_allowed_surface_gap_ls": round(
                combined_radius * policy.max_surface_gap_ratio,
                6,
            ),
            "max_surface_gap_ratio": policy.max_surface_gap_ratio,
        }
        if separation <= threshold:
            return SystemSafetyAssessment(
                system,
                system_id64,
                "dangerous",
                (
                    f"{arrival_star.name} and {companion.name} meet the configured "
                    "dangerous-close-star geometry rule."
                ),
                evidence,
            )
        if separation_basis == "recorded_separation":
            evidence["reason"] = (
                "The recorded phase is outside the threshold, but the orbit's "
                "minimum separation is unavailable."
            )
            unknown_pairs.append(evidence)
        else:
            safe_pairs.append(evidence)

    if unknown_pairs:
        return SystemSafetyAssessment(
            system,
            system_id64,
            "unknown",
            "No dangerous pair was proven, but at least one companion lacks a complete safe orbital envelope.",
            {"unknown_pairs": unknown_pairs, "safe_pairs": safe_pairs},
        )
    return SystemSafetyAssessment(
        system,
        system_id64,
        "safe",
        "Every catalogued companion has a complete orbital envelope outside the configured close-star threshold.",
        {"safe_pairs": safe_pairs},
    )


def filter_route_candidates(
    candidates: Iterable[dict[str, Any]],
    assessments: dict[int, SystemSafetyAssessment],
    policy: RouteSafetyPolicy,
    *,
    id_getter: Callable[[dict[str, Any]], int | None] | None = None,
) -> RouteCandidateFilterResult:
    """Apply assessments to arbitrary candidate dictionaries.

    The generic shape and injectable id accessor keep the policy reusable by
    future pathing modes without coupling it to exobiology fields.
    """

    get_id = id_getter or (lambda candidate: _coerce_system_id(candidate.get("system_id64")))
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unknown_allowed: list[dict[str, Any]] = []
    for candidate in candidates:
        copied = dict(candidate)
        system_id64 = get_id(candidate)
        assessment = assessments.get(system_id64) if system_id64 is not None else None
        if assessment is None:
            assessment = SystemSafetyAssessment(
                str(candidate.get("system") or "Unknown system"),
                system_id64,
                "unknown",
                (
                    "The candidate has no exact id64 geometry record."
                    if system_id64 is None
                    else "No star geometry was returned for the candidate."
                ),
                {"missing": ["system_id64"] if system_id64 is None else ["star records"]},
            )
        copied["route_safety"] = assessment.to_dict()

        should_exclude = assessment.status == "dangerous" or (
            assessment.status == "unknown"
            and policy.unknown_system_policy == "exclude"
        )
        if should_exclude:
            excluded.append(copied)
        else:
            included.append(copied)
            if assessment.status == "unknown":
                unknown_allowed.append(copied)
    return RouteCandidateFilterResult(included, excluded, unknown_allowed)


def _coerce_system_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
