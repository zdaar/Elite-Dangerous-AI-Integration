import json
from pathlib import Path
import sys
from types import SimpleNamespace

from openai.types.chat import ChatCompletionMessageFunctionToolCall
import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.ActionManager import ActionManager
from src.lib.Assistant import Assistant


@pytest.fixture(autouse=True)
def reset_actions():
    original_actions = ActionManager.actions
    ActionManager.actions = {}
    try:
        yield
    finally:
        ActionManager.actions = original_actions


def make_tool_call(name: str, arguments: dict) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        type="function",
        id=f"call_{name}",
        function={"name": name, "arguments": json.dumps(arguments)},
    )


def make_assistant(manager: ActionManager):
    tool_events: list[tuple[list[dict], list[dict], list[str] | None]] = []
    assistant = Assistant.__new__(Assistant)
    assistant.action_manager = manager
    assistant.event_manager = SimpleNamespace(
        add_tool_processing=lambda *_args: None,
        add_tool_call=lambda requests, results, descriptions: tool_events.append(
            (requests, results, descriptions)
        ),
    )
    assistant.tts = SimpleNamespace(say=lambda *_args, **_kwargs: None)
    assistant._get_tts_postprocessing_layers = lambda _states: []
    return assistant, tool_events


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai-chatgpt", False),
        ("openai", True),
        ("custom", True),
    ],
)
def test_action_cache_is_disabled_for_codex_managed_tool_turns(
    provider: str,
    expected: bool,
) -> None:
    assistant = Assistant.__new__(Assistant)
    assistant.config = {
        "llm_provider": provider,
        "use_action_cache_var": True,
    }

    assert assistant._action_cache_enabled() is expected


def test_execute_actions_neutralizes_guidance_next_before_plugin_mutation() -> None:
    manager = ActionManager()
    received_arguments: list[dict] = []
    manager.registerAction(
        "control_exobiology_expedition",
        "Control expedition",
        {},
        lambda args, _states: received_arguments.append(args) or "status returned",
    )
    assistant, tool_events = make_assistant(manager)

    cacheable = assistant.execute_actions(
        [make_tool_call("control_exobiology_expedition", {"operation": "next"})],
        {},
        "Guide-moi ici : qu'est-ce que je fais maintenant ?",
    )

    assert received_arguments == [{"operation": "status"}]
    assert cacheable == []
    recorded_request = tool_events[0][0][0]
    assert json.loads(recorded_request["function"]["arguments"]) == {"operation": "status"}
    assert tool_events[0][1][0]["content"] == "status returned"


def test_execute_actions_preserves_explicit_next_command() -> None:
    manager = ActionManager()
    received_arguments: list[dict] = []
    manager.registerAction(
        "control_exobiology_expedition",
        "Control expedition",
        {},
        lambda args, _states: received_arguments.append(args) or "advanced",
    )
    assistant, _tool_events = make_assistant(manager)
    requested = make_tool_call("control_exobiology_expedition", {"operation": "next"})

    cacheable = assistant.execute_actions([requested], {}, "Nova, prochaine cible.")

    assert received_arguments == [{"operation": "next"}]
    assert cacheable == [requested]


def test_execute_actions_does_not_invoke_blocked_preliminary_lookup() -> None:
    manager = ActionManager()
    lookup_calls: list[dict] = []
    manager.registerAction(
        "lookup_elite_guide",
        "Lookup",
        {},
        lambda args, _states: lookup_calls.append(args) or "should not run",
        action_type="web",
    )
    assistant, tool_events = make_assistant(manager)

    cacheable = assistant.execute_actions(
        [make_tool_call("lookup_elite_guide", {"query": "remaining jumps"})],
        {},
        "Combien de sauts reste-t-il ?",
    )

    assert lookup_calls == []
    assert cacheable == []
    blocked_result = json.loads(tool_events[0][1][0]["content"])
    assert blocked_result["blocked"] is True
    assert "Do not retry" in blocked_result["instruction"]


def test_execute_actions_invokes_managed_guide_for_game_fact_question() -> None:
    manager = ActionManager()
    lookup_calls: list[dict] = []
    manager.registerAction(
        "lookup_elite_guide",
        "Lookup",
        {},
        lambda args, _states: lookup_calls.append(args) or "Wanted is a live bounty state.",
        action_type="web",
    )
    assistant, tool_events = make_assistant(manager)
    requested = make_tool_call("lookup_elite_guide", {"query": "Wanted status"})

    cacheable = assistant.execute_actions(
        [requested],
        {},
        "What does Wanted status mean?",
    )

    assert lookup_calls == [{"query": "Wanted status"}]
    assert cacheable == [requested]
    assert tool_events[0][1][0]["content"] == "Wanted is a live bounty state."


@pytest.mark.parametrize("action_name", ["find_exobiology_targets", "plan_tectonicas_expedition"])
def test_execute_actions_does_not_replace_targets_during_current_body_guidance(action_name: str) -> None:
    manager = ActionManager()
    planner_calls: list[dict] = []
    manager.registerAction(
        action_name,
        "Plan targets",
        {},
        lambda args, _states: planner_calls.append(args) or "should not run",
        action_type="web",
    )
    assistant, tool_events = make_assistant(manager)

    cacheable = assistant.execute_actions(
        [make_tool_call(action_name, {})],
        {},
        "What now on this body?",
    )

    assert planner_calls == []
    assert cacheable == []
    blocked_result = json.loads(tool_events[0][1][0]["content"])
    assert "cannot create or replace" in blocked_result["reason"]
