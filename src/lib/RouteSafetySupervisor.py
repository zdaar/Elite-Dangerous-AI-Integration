from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .RouteSafety import SystemSafetyAssessment


SupervisorAction = Literal[
    "none",
    "route_safe",
    "route_accepted_unknown",
    "plot_boundary",
    "find_bypass",
    "plot_original",
    "manual_bypass_required",
]


@dataclass(frozen=True)
class RouteHop:
    name: str
    system_address: int | None
    coordinates: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class SupervisorDecision:
    action: SupervisorAction
    message: str
    target: RouteHop | None = None
    dangerous: RouteHop | None = None
    hop_number: int | None = None
    unknown_hops: int = 0


class RouteSafetySupervisor:
    """State machine for safe-prefix and one-hop bypass replanning."""

    def __init__(self, *, max_bypass_attempts: int = 5) -> None:
        self.max_bypass_attempts = max_bypass_attempts
        self.phase = "idle"
        self.original_destination: RouteHop | None = None
        self.boundary: RouteHop | None = None
        self.dangerous: RouteHop | None = None
        self.bypass: RouteHop | None = None
        self.forbidden_system_ids: set[int] = set()
        self.bypass_attempts = 0

    @staticmethod
    def _matches(first: RouteHop | None, second: RouteHop | None) -> bool:
        if first is None or second is None:
            return False
        if first.system_address is not None and second.system_address is not None:
            return first.system_address == second.system_address
        return first.name.casefold() == second.name.casefold()

    def reset(self) -> None:
        self.phase = "idle"
        self.original_destination = None
        self.boundary = None
        self.dangerous = None
        self.bypass = None
        self.forbidden_system_ids.clear()
        self.bypass_attempts = 0

    def inspect_route(
        self,
        route: list[RouteHop],
        lookup: Callable[[int], SystemSafetyAssessment | None],
    ) -> SupervisorDecision:
        if len(route) < 2:
            return SupervisorDecision("none", "No multi-system route is available.")
        destination = route[-1]

        if self.phase == "routing_to_boundary" and self._matches(destination, self.boundary):
            return SupervisorDecision(
                "none",
                "Safe-prefix route is ready.",
                target=self.boundary,
            )
        if self.phase == "routing_to_bypass" and self._matches(destination, self.bypass):
            return SupervisorDecision(
                "none",
                "Verified-safe bypass route is ready.",
                target=self.bypass,
            )

        # A route to an unexpected destination is a new commander intent.
        if (
            self.original_destination is not None
            and self.phase not in {"idle", "safe", "replotting_original"}
            and not self._matches(destination, self.original_destination)
        ):
            self.reset()

        first_dangerous: tuple[int, RouteHop, SystemSafetyAssessment] | None = None
        unknown_hops = 0
        for index, hop in enumerate(route[1:], start=1):
            if hop.system_address is None:
                unknown_hops += 1
                continue
            assessment = lookup(hop.system_address)
            if assessment is not None and assessment.status == "dangerous":
                first_dangerous = (index, hop, assessment)
                break
            if assessment is None or assessment.status == "unknown":
                unknown_hops += 1

        if first_dangerous is None:
            if unknown_hops:
                was_replotting_original = self.phase == "replotting_original"
                self.phase = "safe"
                if self.original_destination is None or not was_replotting_original:
                    self.original_destination = destination
                return SupervisorDecision(
                    "route_accepted_unknown",
                    f"Route accepted with {unknown_hops} unevaluated hop(s).",
                    target=destination,
                    unknown_hops=unknown_hops,
                )
            if self.phase == "replotting_original" and self._matches(
                destination,
                self.original_destination,
            ):
                self.phase = "safe"
                return SupervisorDecision(
                    "route_safe",
                    "Replotted route passed close-star validation.",
                    target=destination,
                )
            if self.phase in {"idle", "safe"}:
                self.phase = "safe"
                self.original_destination = destination
                return SupervisorDecision(
                    "route_safe",
                    "Plotted route passed close-star validation.",
                    target=destination,
                )
            return SupervisorDecision("none", "No proven dangerous hop is present.")

        danger_index, dangerous, _assessment = first_dangerous
        if self.original_destination is None or self.phase in {"idle", "safe"}:
            self.original_destination = destination
            self.forbidden_system_ids.clear()
            self.bypass_attempts = 0
        if dangerous.system_address is not None:
            self.forbidden_system_ids.add(dangerous.system_address)
        self.boundary = route[danger_index - 1]
        self.dangerous = dangerous
        self.bypass = None
        self.bypass_attempts += 1
        if self.bypass_attempts > self.max_bypass_attempts:
            self.phase = "manual_required"
            return SupervisorDecision(
                "manual_bypass_required",
                "Automatic bypass attempt limit reached.",
                target=self.boundary,
                dangerous=dangerous,
                hop_number=danger_index,
            )
        if danger_index == 1:
            self.phase = "awaiting_bypass"
            return SupervisorDecision(
                "find_bypass",
                "The next hop is dangerous; find a verified-safe intermediate.",
                target=self.boundary,
                dangerous=dangerous,
                hop_number=danger_index,
            )
        self.phase = "routing_to_boundary"
        return SupervisorDecision(
            "plot_boundary",
            "Shorten the route to the last safe hop.",
            target=self.boundary,
            dangerous=dangerous,
            hop_number=danger_index,
        )

    def on_jump(self, arrived: RouteHop) -> SupervisorDecision:
        if self.phase == "routing_to_boundary" and self._matches(arrived, self.boundary):
            self.phase = "awaiting_bypass"
            return SupervisorDecision(
                "find_bypass",
                "Safe-prefix boundary reached; find a verified-safe intermediate.",
                target=arrived,
            )
        if self.phase == "routing_to_bypass" and self._matches(arrived, self.bypass):
            self.phase = "replotting_original"
            return SupervisorDecision(
                "plot_original",
                "Verified-safe bypass reached; replot the original destination.",
                target=self.original_destination,
            )
        return SupervisorDecision("none", "Jump does not advance the bypass workflow.")

    def set_bypass(self, bypass: RouteHop) -> SupervisorDecision:
        if self.phase != "awaiting_bypass":
            return SupervisorDecision("none", "No bypass waypoint is currently required.")
        self.bypass = bypass
        self.phase = "routing_to_bypass"
        return SupervisorDecision(
            "none",
            "Verified-safe bypass selected.",
            target=bypass,
        )

    def require_manual_bypass(self) -> SupervisorDecision:
        self.phase = "manual_required"
        return SupervisorDecision(
            "manual_bypass_required",
            "No deterministic verified-safe intermediate was available.",
            target=self.boundary,
        )
