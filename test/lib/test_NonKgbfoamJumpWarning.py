import socket

import pytest

from src.lib.Event import GameEvent, StatusEvent
from src.lib.NonKgbfoamJumpWarning import (
    KGBFOAM_CLASSES,
    OFFICIAL_NON_KGBFOAM_CLASSES,
    NonKgbfoamJumpWarningController,
    configured_warning_language,
    format_star_warning,
    get_star_class_profile,
)


OFFICIAL_JOURNAL_NON_KGBFOAM_CLASSES = {
    "L", "T", "Y",
    "TTS", "AeBe",
    "W", "WN", "WNC", "WC", "WO",
    "CS", "C", "CN", "CJ", "CH", "CHd", "MS", "S",
    "D", "DA", "DAB", "DAO", "DAZ", "DAV", "DB", "DBZ", "DBV",
    "DO", "DOV", "DQ", "DC", "DCV", "DX",
    "N", "H", "X", "SupermassiveBlackHole",
    "A_BlueWhiteSuperGiant", "B_BlueWhiteSuperGiant", "F_WhiteSuperGiant",
    "M_RedSuperGiant", "M_RedGiant", "K_OrangeGiant",
    "RoguePlanet", "Nebula", "StellarRemnantNebula",
}


def game(event: str, **content: object) -> GameEvent:
    return GameEvent(
        content={"event": event, "timestamp": "2026-08-06T00:00:00Z", **content},
        historic=False,
    )


def status(
    charging: bool,
    *,
    hyperdrive: bool | None = True,
    destination_name: str = "Next System",
    destination_address: int = 42,
) -> StatusEvent:
    flags2 = (
        {"FsdHyperdriveCharging": hyperdrive}
        if hyperdrive is not None
        else None
    )
    return StatusEvent(status={
        "event": "Status",
        "flags": {"FsdCharging": charging},
        "flags2": flags2,
        "Destination": {
            "System": destination_address,
            "Body": 0,
            "Name": destination_name,
        },
    })


def target(star_class: object, name: str = "Next System", address: int = 42) -> GameEvent:
    return game(
        "FSDTarget",
        Name=name,
        SystemAddress=address,
        StarClass=star_class,
    )


def decide(
    controller: NonKgbfoamJumpWarningController,
    event: GameEvent | StatusEvent,
    *,
    unknown: bool = False,
):
    return controller.process(
        event,
        warning_enabled=True,
        unknown_warning_enabled=unknown,
    )


def test_complete_official_non_kgbfoam_mapping_has_operational_fields() -> None:
    assert OFFICIAL_NON_KGBFOAM_CLASSES == OFFICIAL_JOURNAL_NON_KGBFOAM_CLASSES
    for star_class in OFFICIAL_JOURNAL_NON_KGBFOAM_CLASSES:
        profile = get_star_class_profile(star_class)
        assert profile is not None
        assert profile.normalized_class
        assert profile.family
        assert profile.scoopable in {True, False, None}
        assert profile.appearance_en and profile.appearance_fr
        assert profile.arrival_hazard_en and profile.arrival_hazard_fr
        assert profile.jet_cone_supercharging in {True, False, None}
        assert profile.recommended_action_en and profile.recommended_action_fr


@pytest.mark.parametrize("star_class", sorted(KGBFOAM_CLASSES))
def test_every_kgbfoam_class_is_silent(star_class: str) -> None:
    controller = NonKgbfoamJumpWarningController()
    assert decide(controller, target(star_class)) is None
    assert decide(controller, status(True)) is None


@pytest.mark.parametrize(
    ("star_class", "family", "scoopable", "jet_cone"),
    [
        ("T", "brown_dwarf", False, False),
        ("TTS", "protostar", False, False),
        ("WN", "wolf_rayet", False, False),
        ("CHd", "carbon_star", False, False),
        ("DA", "white_dwarf", False, True),
        ("N", "neutron_star", False, True),
        ("H", "black_hole", False, False),
        ("SupermassiveBlackHole", "supermassive_black_hole", False, False),
        ("K_OrangeGiant", "giant_or_supergiant", True, False),
        ("X", "journal_placeholder", None, None),
    ],
)
def test_representative_non_kgbfoam_classes_have_exact_category(
    star_class: str,
    family: str,
    scoopable: bool | None,
    jet_cone: bool | None,
) -> None:
    profile = get_star_class_profile(star_class)
    assert profile is not None
    assert profile.family == family
    assert profile.scoopable is scoopable
    assert profile.jet_cone_supercharging is jet_cone


def test_immediate_target_wins_over_final_route_destination() -> None:
    controller = NonKgbfoamJumpWarningController()
    # Plotting a route with a non-KGBFOAM final destination never warns.
    assert decide(controller, game("NavRoute", Route=[
        {"StarSystem": "Current", "StarClass": "G"},
        {"StarSystem": "Immediate", "StarClass": "K"},
        {"StarSystem": "Final", "StarClass": "N"},
    ])) is None
    assert decide(controller, target("K", "Immediate", 42)) is None
    assert decide(controller, status(True, destination_name="Immediate")) is None

    # On a new cycle, the immediate FSDTarget is non-KGBFOAM even though the
    # final route entry is scoopable.
    assert decide(controller, status(False, destination_name="Immediate")) is None
    assert decide(controller, game("NavRoute", Route=[
        {"StarSystem": "Current", "StarClass": "G"},
        {"StarSystem": "Dark Hop", "StarClass": "T"},
        {"StarSystem": "Final", "StarClass": "O"},
    ])) is None
    assert decide(controller, target("T", "Dark Hop", 43)) is None
    decision = decide(
        controller,
        status(True, destination_name="Dark Hop", destination_address=43),
    )
    assert decision is not None
    assert decision.star_class == "T"
    assert decision.target_name == "Dark Hop"


def test_one_warning_per_charge_cycle_across_repeated_status_and_fallback() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("T"))
    first = decide(controller, status(True))
    assert first is not None
    assert decide(controller, status(True)) is None
    assert decide(controller, StatusEvent(status={
        "event": "FsdCharging",
        "JumpType": "Hyperspace",
    })) is None
    assert decide(controller, game(
        "StartJump",
        JumpType="Hyperspace",
        StarSystem="Next System",
        SystemAddress=42,
        StarClass="T",
    )) is None


def test_cancel_and_retry_creates_a_new_warning_cycle() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("Y"))
    first = decide(controller, status(True))
    assert first is not None
    assert decide(controller, status(False)) is None
    retry = decide(controller, status(True))
    assert retry is not None
    assert retry.cycle_id != first.cycle_id


def test_destination_change_before_charge_uses_new_authoritative_target() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("T", "Old Target", 10))
    decide(controller, target("H", "New Target", 11))
    decision = decide(
        controller,
        status(True, destination_name="New Target", destination_address=11),
    )
    assert decision is not None
    assert decision.star_class == "H"
    assert decision.target_name == "New Target"


def test_stale_target_class_is_not_reused_for_a_different_status_destination() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("N", "Old Target", 10))
    assert decide(
        controller,
        status(True, destination_name="Different Target", destination_address=11),
    ) is None


@pytest.mark.parametrize("star_class", [None, "", "???", 123, {"bad": "value"}])
def test_missing_or_malformed_class_is_silent_by_default(star_class: object) -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target(star_class))
    assert decide(controller, status(True)) is None


def test_unknown_class_warning_is_separately_opt_in() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("???"), unknown=True)
    decision = decide(controller, status(True), unknown=True)
    assert decision is not None
    assert decision.kind == "unknown"
    assert decision.profile is None


def test_route_clear_does_not_warn_or_discard_a_selected_single_jump_target() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("L"))
    assert decide(controller, game("NavRouteClear")) is None
    decision = decide(controller, status(True))
    assert decision is not None
    assert decision.star_class == "L"


def test_successful_jump_closes_cycle_and_next_target_can_warn() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("T", "First", 1))
    first = decide(
        controller,
        status(True, destination_name="First", destination_address=1),
    )
    assert first is not None
    decide(controller, target("H", "Second", 2))
    assert decide(controller, game("FSDJump", StarSystem="First", SystemAddress=1)) is None
    second = decide(
        controller,
        status(True, destination_name="Second", destination_address=2),
    )
    assert second is not None
    assert second.star_class == "H"
    assert second.cycle_id != first.cycle_id


def test_missing_hyperdrive_flag_waits_for_authoritative_start_jump_fallback() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("N"))
    assert decide(controller, status(True, hyperdrive=None)) is None
    decision = decide(controller, game(
        "StartJump",
        JumpType="Hyperspace",
        StarSystem="Next System",
        SystemAddress=42,
        StarClass="N",
    ))
    assert decision is not None
    assert decision.trigger == "start_jump"
    assert decision.star_class == "N"


def test_supercruise_charge_never_warns_against_selected_route_target() -> None:
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("T"))
    assert decide(controller, status(True, hyperdrive=False)) is None
    assert decide(controller, game("StartJump", JumpType="Supercruise")) is None


def test_warning_generation_has_no_llm_or_network_dependency(monkeypatch) -> None:
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden during warning generation")

    monkeypatch.setattr(socket, "socket", fail_network)
    controller = NonKgbfoamJumpWarningController()
    decide(controller, target("T"))
    decision = decide(controller, status(True))
    assert decision is not None and decision.profile is not None
    text = format_star_warning(decision.profile, "fr")
    assert "naine brune de classe T" in text
    assert "Non scoopable" in text
    assert "panne sèche" in text


def test_configured_language_prefers_active_character() -> None:
    config = {
        "active_character_index": 1,
        "characters": [
            {"personality_language": "English"},
            {"personality_language": "Français"},
        ],
        "tts_language": "en",
    }
    assert configured_warning_language(config) == "fr"
