from src.lib.CloseStarJumpGuard import CloseStarJumpGuardController
from src.lib.Event import GameEvent, StatusEvent
from src.lib.RouteSafety import SystemSafetyAssessment


def game(event: str, **content) -> GameEvent:
    return GameEvent(
        content={"event": event, "timestamp": "2026-08-06T00:00:00Z", **content},
        historic=False,
    )


def status(charging: bool, *, hyperspace: bool = True, address: int = 42) -> StatusEvent:
    return StatusEvent(status={
        "event": "Status",
        "flags": {"FsdCharging": charging},
        "flags2": {"FsdHyperdriveCharging": hyperspace},
        "Destination": {"System": address, "Name": "Next"},
    })


def assessment(status_value: str, address: int = 42) -> SystemSafetyAssessment:
    return SystemSafetyAssessment("Next", address, status_value, "test", {})  # type: ignore[arg-type]


def test_dangerous_immediate_hop_emits_once_per_charge_cycle() -> None:
    controller = CloseStarJumpGuardController()
    controller.process(
        game("FSDTarget", Name="Next", SystemAddress=42, StarClass="G"),
        enabled=True,
        lookup=lambda _: assessment("dangerous"),
    )

    first = controller.process(
        status(True),
        enabled=True,
        lookup=lambda _: assessment("dangerous"),
    )
    repeated = controller.process(
        status(True),
        enabled=True,
        lookup=lambda _: assessment("dangerous"),
    )
    controller.process(status(False), enabled=True, lookup=lambda _: assessment("dangerous"))
    retry = controller.process(status(True), enabled=True, lookup=lambda _: assessment("dangerous"))

    assert first is not None and first.trigger == "fsd_charging"
    assert repeated is None
    assert retry is not None


def test_safe_unknown_disabled_and_supercruise_never_cancel() -> None:
    for enabled, hyperspace, safety in (
        (True, True, "safe"),
        (True, True, "unknown"),
        (False, True, "dangerous"),
        (True, False, "dangerous"),
    ):
        controller = CloseStarJumpGuardController()
        controller.process(
            game("FSDTarget", Name="Next", SystemAddress=42),
            enabled=enabled,
            lookup=lambda _: assessment(safety),
        )
        assert controller.process(
            status(True, hyperspace=hyperspace),
            enabled=enabled,
            lookup=lambda _: assessment(safety),
        ) is None


def test_stale_target_assessment_is_not_applied_to_new_destination() -> None:
    controller = CloseStarJumpGuardController()
    controller.process(
        game("FSDTarget", Name="Old", SystemAddress=41),
        enabled=True,
        lookup=lambda _: assessment("dangerous", 41),
    )

    decision = controller.process(
        status(True, address=42),
        enabled=True,
        lookup=lambda address: assessment("dangerous", address) if address == 41 else None,
    )

    assert decision is None


def test_start_jump_is_deterministic_fallback_when_status_detail_is_missing() -> None:
    controller = CloseStarJumpGuardController()
    decision = controller.process(
        game(
            "StartJump",
            JumpType="Hyperspace",
            StarSystem="Next",
            SystemAddress=42,
            StarClass="G",
        ),
        enabled=True,
        lookup=lambda _: assessment("dangerous"),
    )

    assert decision is not None
    assert decision.trigger == "start_jump"
