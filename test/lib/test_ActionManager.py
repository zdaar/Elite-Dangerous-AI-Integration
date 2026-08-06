import json
from collections.abc import Generator
from pathlib import Path
import sys

import pytest
from openai.types.chat import ChatCompletionMessageFunctionToolCall

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.ActionManager import ActionManager


@pytest.fixture(autouse=True)
def reset_actions() -> Generator[None, None, None]:
    original_actions = ActionManager.actions
    ActionManager.actions = {}
    try:
        yield
    finally:
        ActionManager.actions = original_actions


def make_tool_call(name: str, arguments: dict | None = None) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        type="function",
        id="call_test",
        function={
            "name": name,
            "arguments": json.dumps(arguments or {}),
        },
    )


def test_run_action_returns_existing_final_result_shape() -> None:
    manager = ActionManager()

    def action(args: dict, projected_states: dict) -> str:
        return f"done {args['value']}"

    manager.registerAction("testAction", "Test action", {}, action)

    result = manager.runAction(make_tool_call("testAction", {"value": 42}), {})

    assert result == {
        "tool_call_id": "call_test",
        "role": "tool",
        "name": "testAction",
        "content": "done 42",
    }


def test_run_action_emits_processing_results_from_iterator() -> None:
    manager = ActionManager()
    processing_results: list[tuple[str, str, object]] = []

    def action(args: dict, projected_states: dict):
        yield "starting"
        yield {"status": "working"}
        return "finished"

    manager.registerAction("testAction", "Test action", {}, action)

    result = manager.runAction(
        make_tool_call("testAction"),
        {},
        processing_callback=lambda tool_call_id, name, content: processing_results.append((tool_call_id, name, content)),
    )

    assert processing_results == [
        ("call_test", "testAction", "starting"),
        ("call_test", "testAction", {"status": "working"}),
    ]
    assert result == {
        "tool_call_id": "call_test",
        "role": "tool",
        "name": "testAction",
        "content": "finished",
    }


def test_run_action_iterator_exception_returns_error_result() -> None:
    manager = ActionManager()
    processing_results: list[tuple[str, str, object]] = []

    def action(args: dict, projected_states: dict):
        yield "starting"
        raise ValueError("failed")

    manager.registerAction("testAction", "Test action", {}, action)

    result = manager.runAction(
        make_tool_call("testAction"),
        {},
        processing_callback=lambda tool_call_id, name, content: processing_results.append((tool_call_id, name, content)),
    )

    assert processing_results == [("call_test", "testAction", "starting")]
    assert result["tool_call_id"] == "call_test"
    assert result["role"] == "tool"
    assert result["name"] == "testAction"
    assert str(result["content"]).startswith("ERROR: ValueError")


@pytest.mark.parametrize(
    ("allowed_actions", "is_registered"),
    [
        ({}, False),
        ({"testPermission": False}, False),
        ({"testPermission": True}, True),
    ],
)
def test_registration_requires_explicitly_enabled_permission(
    allowed_actions: dict[str, bool],
    is_registered: bool,
) -> None:
    manager = ActionManager()
    manager.set_allowed_actions(allowed_actions)

    manager.registerAction(
        "testAction",
        "Test action",
        {},
        lambda args, states: "done",
        permission="testPermission",
    )

    assert ("testAction" in manager.actions) is is_registered


def test_tool_list_requires_explicitly_enabled_permission() -> None:
    manager = ActionManager()
    manager.set_allowed_actions({
        "enabledPermission": True,
        "disabledPermission": True,
        "missingPermission": True,
    })

    for action_name, permission in [
        ("enabledAction", "enabledPermission"),
        ("disabledAction", "disabledPermission"),
        ("missingAction", "missingPermission"),
    ]:
        manager.registerAction(
            action_name,
            "Test action",
            {},
            lambda args, states: "done",
            permission=permission,
        )

    tools = manager.getToolsList(
        "ship",
        True,
        False,
        False,
        {
            "enabledPermission": True,
            "disabledPermission": False,
        },
    )

    assert [tool["function"]["name"] for tool in tools] == ["enabledAction"]


def test_permissionless_actions_remain_available() -> None:
    manager = ActionManager()
    manager.set_allowed_actions({})
    manager.registerAction(
        "permissionlessAction",
        "Test action",
        {},
        lambda args, states: "done",
    )

    tools = manager.getToolsList("ship", True, False, False, {})

    assert [tool["function"]["name"] for tool in tools] == [
        "permissionlessAction"
    ]


@pytest.mark.parametrize(
    "utterance",
    [
        "Guide-moi ici, je ne sais pas quoi faire.",
        "What now?",
        "What next on this body?",
        "Quel est le statut de l'expédition ?",
    ],
)
def test_routing_guard_converts_accidental_next_to_status(utterance: str) -> None:
    action = make_tool_call("control_exobiology_expedition", {"operation": "next"})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is not None
    assert json.loads(decision.action.function.arguments) == {"operation": "status"}
    assert decision.cacheable is False
    assert json.loads(action.function.arguments) == {"operation": "next"}


@pytest.mark.parametrize(
    "utterance",
    [
        "Next.",
        "Nova, prochaine cible.",
        "Nova, système suivant.",
        "Expédition next.",
        "Rien ici. Opération next.",
        "Skip this target.",
    ],
)
def test_routing_guard_preserves_explicit_next_commands(utterance: str) -> None:
    action = make_tool_call("control_exobiology_expedition", {"operation": "next"})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is action
    assert decision.reason is None
    assert decision.cacheable is True


@pytest.mark.parametrize("action_name", ["find_exobiology_targets", "plan_tectonicas_expedition"])
def test_routing_guard_blocks_target_replacement_during_current_body_guidance(action_name: str) -> None:
    action = make_tool_call(action_name, {})

    decision = ActionManager.guard_action(
        action,
        "Guide-moi ici, qu'est-ce que je fais maintenant ?",
    )

    assert decision.action is None
    assert decision.cacheable is False
    assert "cannot create or replace" in str(decision.reason)


@pytest.mark.parametrize(
    ("action_name", "utterance"),
    [
        ("find_exobiology_targets", "Guide-moi ici, puis trouve une nouvelle cible rentable à la place."),
        ("plan_tectonicas_expedition", "What now? Actually, replan the expedition with ten systems."),
    ],
)
def test_routing_guard_preserves_explicit_replan_during_guidance(action_name: str, utterance: str) -> None:
    action = make_tool_call(action_name, {})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is action
    assert decision.cacheable is True


@pytest.mark.parametrize("action_name", ["lookup_elite_guide", "web_search_agent", "remember_memories"])
@pytest.mark.parametrize("utterance", ["How many jumps are left?", "Guide-moi ici, que faire maintenant ?"])
def test_routing_guard_blocks_preliminary_lookups_for_direct_status(
    action_name: str,
    utterance: str,
) -> None:
    action = make_tool_call(action_name, {"query": "route"})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is None
    assert decision.cacheable is False
    assert "preliminary lookup blocked" in str(decision.reason)


@pytest.mark.parametrize("action_name", ["lookup_elite_guide", "web_search_agent", "remember_memories"])
def test_routing_guard_blocks_lookup_when_direct_tool_is_already_selected(action_name: str) -> None:
    action = make_tool_call(action_name, {"query": "target"})

    decision = ActionManager.guard_action(
        action,
        "Do it.",
        {action_name, "plotToTarget"},
    )

    assert decision.action is None


def test_routing_guard_blocks_lookup_when_utterance_names_registered_direct_tool() -> None:
    manager = ActionManager()
    manager.registerAction("plotToTarget", "Plot", {}, lambda _args, _states: "done")
    lookup = make_tool_call("lookup_elite_guide", {"query": "plot"})

    decision = manager.guard_action(
        lookup,
        "Appelle uniquement plotToTarget avec le système exact.",
    )

    assert decision.action is None


@pytest.mark.parametrize(
    ("action_name", "utterance"),
    [
        ("lookup_elite_guide", "Consulte le guide pour expliquer le bonus First Logged."),
        ("web_search_agent", "Search the web for the current community goal."),
        ("remember_memories", "Search memories for Melvin's cats."),
    ],
)
def test_routing_guard_preserves_explicit_lookup_requests(action_name: str, utterance: str) -> None:
    action = make_tool_call(action_name, {"query": "requested information"})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is action
    assert decision.cacheable is True


@pytest.mark.parametrize(
    "utterance",
    [
        "What does Wanted status mean?",
        "Que signifie le statut Wanted ?",
        "How does Powerplay progress work?",
    ],
)
def test_routing_guard_preserves_managed_guide_for_game_fact_questions(utterance: str) -> None:
    action = make_tool_call("lookup_elite_guide", {"query": utterance})

    decision = ActionManager.guard_action(action, utterance)

    assert decision.action is action
    assert decision.reason is None
    assert decision.cacheable is True


@pytest.mark.parametrize("action_name", ["web_search_agent", "remember_memories"])
def test_routing_guard_prefers_managed_guide_over_external_lookup_for_game_facts(
    action_name: str,
) -> None:
    action = make_tool_call(action_name, {"query": "Wanted status"})

    decision = ActionManager.guard_action(
        action,
        "What does Wanted status mean?",
        {action_name, "lookup_elite_guide"},
    )

    assert decision.action is None
    assert decision.cacheable is False
    assert "managed Elite guide is authoritative" in str(decision.reason)


def test_routing_guard_still_blocks_managed_guide_for_live_expedition_status() -> None:
    action = make_tool_call("lookup_elite_guide", {"query": "expedition status"})

    decision = ActionManager.guard_action(
        action,
        "Quel est le statut de l'expédition ?",
    )

    assert decision.action is None
    assert decision.cacheable is False
