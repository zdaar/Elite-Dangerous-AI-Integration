from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .Event import Event, GameEvent, StatusEvent
from .RouteSafety import SystemSafetyAssessment


@dataclass(frozen=True)
class GuardTarget:
    name: str | None
    system_address: int | None


@dataclass(frozen=True)
class CloseStarGuardDecision:
    trigger: Literal["fsd_charging", "start_jump"]
    target: GuardTarget
    assessment: SystemSafetyAssessment


class CloseStarJumpGuardController:
    """Select a cached dangerous assessment once per hyperspace charge.

    Data acquisition and key presses stay outside this state machine. This
    keeps the charge-time decision local, deterministic, and testable.
    """

    def __init__(self) -> None:
        self.current_target: GuardTarget | None = None
        self.charge_active = False
        self.decision_emitted = False

    @staticmethod
    def _address(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _name(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def _target_for_status(self, status: dict[str, object]) -> GuardTarget | None:
        target = self.current_target
        destination = status.get("Destination")
        if not isinstance(destination, dict):
            return target
        address = self._address(destination.get("System"))
        name = self._name(destination.get("Name"))
        if target is None:
            return GuardTarget(name, address)
        if address is not None and target.system_address != address:
            return GuardTarget(name, address)
        if (
            address is None
            and name is not None
            and target.name is not None
            and name.casefold() != target.name.casefold()
        ):
            return GuardTarget(name, None)
        return target

    def _decision(
        self,
        target: GuardTarget | None,
        trigger: Literal["fsd_charging", "start_jump"],
        lookup: Callable[[int], SystemSafetyAssessment | None],
    ) -> CloseStarGuardDecision | None:
        if self.decision_emitted or target is None or target.system_address is None:
            return None
        assessment = lookup(target.system_address)
        if assessment is None or assessment.status != "dangerous":
            return None
        self.decision_emitted = True
        return CloseStarGuardDecision(trigger, target, assessment)

    def process(
        self,
        event: Event,
        *,
        enabled: bool,
        lookup: Callable[[int], SystemSafetyAssessment | None],
    ) -> CloseStarGuardDecision | None:
        if isinstance(event, GameEvent):
            event_name = event.content.get("event")
            if event_name == "FSDTarget":
                self.current_target = GuardTarget(
                    self._name(event.content.get("Name")),
                    self._address(event.content.get("SystemAddress")),
                )
                return None
            if event_name == "FSDJump":
                self.charge_active = False
                self.decision_emitted = False
                return None
            if event_name in {"LoadGame", "Shutdown"}:
                self.current_target = None
                self.charge_active = False
                self.decision_emitted = False
                return None
            if event_name == "StartJump" and event.content.get("JumpType") == "Hyperspace":
                if not enabled:
                    return None
                target = GuardTarget(
                    self._name(event.content.get("StarSystem")),
                    self._address(event.content.get("SystemAddress")),
                )
                return self._decision(target, "start_jump", lookup)
            return None

        if not isinstance(event, StatusEvent):
            return None
        event_name = event.status.get("event")
        if event_name == "Status":
            flags = event.status.get("flags")
            if not isinstance(flags, dict):
                return None
            is_charging = bool(flags.get("FsdCharging"))
            if not is_charging:
                self.charge_active = False
                self.decision_emitted = False
                return None
            if self.charge_active:
                return None
            self.charge_active = True
            flags2 = event.status.get("flags2")
            if not isinstance(flags2, dict) or flags2.get("FsdHyperdriveCharging") is not True:
                return None
            if not enabled:
                return None
            return self._decision(
                self._target_for_status(event.status),
                "fsd_charging",
                lookup,
            )
        if event_name == "FsdCharging":
            if self.charge_active:
                return None
            self.charge_active = True
            if not enabled or event.status.get("JumpType") != "Hyperspace":
                return None
            return self._decision(self.current_target, "fsd_charging", lookup)
        return None


def format_close_star_guard_warning(
    decision: CloseStarGuardDecision,
    language: Literal["en", "fr"],
    *,
    cancelled: bool,
) -> str:
    system = decision.target.name or decision.assessment.system
    if language == "fr":
        prefix = "Saut hyperspatial annulé." if cancelled else "Danger stellaire détecté. Annulation automatique impossible."
        return (
            f"{prefix} {system} contient une étoile compagne dangereusement proche de l'étoile d'arrivée. "
            "Trace manuellement une route qui contourne ce système."
        )
    prefix = "Hyperspace jump cancelled." if cancelled else "Close-star danger detected. Automatic cancellation failed."
    return (
        f"{prefix} {system} has a companion dangerously close to the arrival star. "
        "Plot a manual route around this system."
    )


def format_unsafe_plotted_route_warning(
    dangerous_system: str,
    last_safe_system: str,
    hop: int,
    language: Literal["en", "fr"],
) -> str:
    if language == "fr":
        return (
            f"Route marquée dangereuse au saut {hop} : {dangerous_system}. "
            f"La portion sûre se termine à {last_safe_system}. Nova annulera la charge vers le système dangereux ; "
            "elle va maintenant tracer cette portion, puis chercher un intermédiaire KGBFOAM sûr."
        )
    return (
        f"Route marked unsafe at jump {hop}: {dangerous_system}. "
        f"The safe prefix ends at {last_safe_system}. Nova will cancel the charge into the dangerous system; "
        "she will now plot that prefix, then look for a safe KGBFOAM intermediate."
    )
