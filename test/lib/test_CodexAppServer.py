from pathlib import Path
import json
import os
import sys

import pytest

from src.lib.CodexAppServer import (
    CodexAppServerClient,
    CodexAppServerResult,
    _CodexAppServerNoFinalResponse,
    _app_server_argv,
)


FAKE_APP_SERVER = r'''
import json
import sys

dynamic_tools = []

def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()

for raw_line in sys.stdin:
    message = json.loads(raw_line)
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        assert params["capabilities"]["experimentalApi"] is True
        send({"id": request_id, "result": {"serverInfo": {"name": "fake"}}})
    elif method == "initialized":
        continue
    elif method == "account/read":
        send({"id": request_id, "result": {"account": {"type": "chatgpt", "planType": "plus"}, "requiresOpenaiAuth": True}})
    elif method == "thread/start":
        assert params["model"] == "gpt-5.6-terra"
        assert params["approvalPolicy"] == "never"
        assert params["sandbox"] == "read-only"
        assert params["ephemeral"] is True
        assert params["config"]["mcp_servers"] == {}
        assert params["config"]["features"]["shell_tool"] is False
        assert params["config"]["include_skill_instructions"] is False
        dynamic_tools = params.get("dynamicTools") or []
        send({"id": request_id, "result": {"thread": {"id": "thread-test"}}})
    elif method == "thread/inject_items":
        send({"id": request_id, "result": {}})
    elif method == "turn/start":
        assert params["effort"] == "low"
        send({"id": request_id, "result": {"turn": {"id": "turn-test", "status": "inProgress", "items": []}}})
        if dynamic_tools:
            tool = dynamic_tools[0]
            assert tool["type"] == "function"
            assert tool["inputSchema"]["type"] == "object"
            send({
                "id": 900,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-test",
                    "turnId": "turn-test",
                    "callId": "call-native-1",
                    "namespace": None,
                    "tool": tool["name"],
                    "arguments": {"operation": "next"},
                },
            })
            send({
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-test",
                    "turnId": "turn-test",
                    "tokenUsage": {
                        "last": {"inputTokens": 15, "cachedInputTokens": 2, "outputTokens": 3, "reasoningOutputTokens": 1, "totalTokens": 18}
                    },
                },
            })
        else:
            send({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-test",
                    "turnId": "turn-test",
                    "item": {"type": "agentMessage", "id": "msg-1", "text": "Target confirmed.", "phase": "final_answer", "memoryCitation": None},
                },
            })
            send({
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-test",
                    "turnId": "turn-test",
                    "tokenUsage": {
                        "last": {"inputTokens": 12, "cachedInputTokens": 3, "outputTokens": 4, "reasoningOutputTokens": 2, "totalTokens": 16}
                    },
                },
            })
            send({
                "method": "turn/completed",
                "params": {"threadId": "thread-test", "turn": {"id": "turn-test", "status": "completed", "items": []}},
            })
    elif request_id == 900 and method is None:
        result = message["result"]
        assert result["success"] is True
        assert result["contentItems"][0]["type"] == "inputText"
        tool_output = result["contentItems"][0]["text"]
        send({
            "method": "item/completed",
            "params": {
                "threadId": "thread-test",
                "turnId": "turn-test",
                "item": {
                    "type": "dynamicToolCall",
                    "id": "tool-1",
                    "tool": dynamic_tools[0]["name"],
                    "status": "completed",
                    "contentItems": result["contentItems"],
                    "success": True,
                },
            },
        })
        send({
            "method": "item/completed",
            "params": {
                "threadId": "thread-test",
                "turnId": "turn-test",
                "item": {
                    "type": "agentMessage",
                    "id": "msg-after-tool",
                    "text": "Tool result received: " + tool_output,
                    "phase": "final_answer",
                    "memoryCitation": None,
                },
            },
        })
        send({
            "method": "turn/completed",
            "params": {"threadId": "thread-test", "turn": {"id": "turn-test", "status": "completed", "items": []}},
        })
'''


def _client(tmp_path: Path) -> CodexAppServerClient:
    script = tmp_path / "fake_app_server.py"
    script.write_text(FAKE_APP_SERVER, encoding="utf-8")
    return CodexAppServerClient(f'"{sys.executable}" "{script}"', timeout_seconds=5)


def test_windows_nvm_cmd_shim_uses_comspec() -> None:
    codex_cmd = r"C:\Users\Commander\scoop apps\nvm\nodejs\codex.cmd"
    argv = _app_server_argv(
        "codex",
        platform_name="nt",
        executable_resolver=lambda executable: codex_cmd if executable == "codex" else None,
        command_processor=r"C:\Windows\System32\cmd.exe",
    )

    assert argv[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert "codex.cmd" in argv[4]
    assert "app-server" in argv[4]


def test_windows_codex_fallback_finds_nvm_cmd_when_which_misses() -> None:
    expected = r"C:\Users\Commander\scoop\apps\nvm\current\nodejs\nodejs\codex.cmd"
    argv = _app_server_argv(
        "codex",
        platform_name="nt",
        executable_resolver=lambda _: None,
        command_processor=r"C:\Windows\System32\cmd.exe",
        environment={
            "USERPROFILE": r"C:\Users\Commander",
            "APPDATA": r"C:\Users\Commander\AppData\Roaming",
            "PATH": r"C:\Windows\System32;C:\Windows",
        },
        path_exists=lambda candidate: candidate == expected,
    )

    assert expected in argv[4]
    assert "app-server" in argv[4]


def test_app_server_uses_native_dynamic_tool_and_preserves_call_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[
            {"role": "system", "content": "Be operational."},
            {"role": "user", "content": "Next target."},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "control_exobiology_expedition",
                    "description": "Control the active expedition.",
                    "parameters": {
                        "type": "object",
                        "properties": {"operation": {"type": "string"}},
                        "required": ["operation"],
                    },
                },
            }
        ],
    )

    assert result.text is None
    assert result.tool_calls == [
        {
            "id": "call-native-1",
            "name": "control_exobiology_expedition",
            "arguments": json.dumps({"operation": "next"}),
        }
    ]
    assert result.usage == {
        "input_tokens": 15,
        "cached_tokens": 2,
        "output_tokens": 3,
        "reasoning_tokens": 1,
        "total_tokens": 18,
    }


def test_app_server_returns_final_text_and_usage(tmp_path: Path) -> None:
    result = _client(tmp_path).generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[{"role": "user", "content": "Status."}],
    )

    assert result.text == "Target confirmed."
    assert result.tool_calls == []
    assert result.usage == {
        "input_tokens": 12,
        "cached_tokens": 3,
        "output_tokens": 4,
        "reasoning_tokens": 2,
        "total_tokens": 16,
    }


def test_app_server_replays_covas_tool_history_as_response_items() -> None:
    client = CodexAppServerClient("codex")
    _, _, history, turn_text = client._prepare_messages(
        [
            {"role": "system", "content": "Be concise."},
            {"role": "tool", "tool_call_id": "call-7", "content": "Route plotted"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-7",
                        "type": "function",
                        "function": {"name": "plotToTarget", "arguments": '{"target":"A"}'},
                    }
                ],
            },
        ]
    )

    assert history == [
        {
            "type": "function_call",
            "call_id": "call-7",
            "name": "plotToTarget",
            "arguments": '{"target":"A"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-7",
            "output": "Route plotted",
        },
    ]
    assert turn_text.startswith("Continue the COVAS conversation")


def _live_probe_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "probe_action",
                "description": "A harmless integration-test action.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_app_server_continues_same_turn_with_covas_tool_result(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[{"role": "user", "content": "Run the probe."}],
        tools=_live_probe_tools(),
    )
    assert len(first.tool_calls) == 1
    tool_call = first.tool_calls[0]

    final = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[
            {"role": "user", "content": "Run the probe."},
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": "route-ready",
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                ],
            },
        ],
        tools=_live_probe_tools(),
    )

    assert final.tool_calls == []
    assert final.text == "Tool result received: route-ready"
    assert client._pending_turn is None


@pytest.mark.parametrize(
    "initial_messages,continuation_addition",
    [
        (
            [{"role": "user", "content": "Run the probe."}],
            {"role": "user", "content": "Cancel that; show live status instead."},
        ),
        (
            [
                {"role": "user", "content": "Run the probe."},
                {"role": "user", "content": "[Game status] Fuel: 12.0"},
            ],
            {"role": "user", "content": "[Game status] Fuel: 11.5"},
        ),
    ],
    ids=["new-commander-message", "changed-game-status"],
)
def test_new_prompt_information_closes_pending_turn_and_replays_full_prompt(
    tmp_path: Path,
    initial_messages: list[dict],
    continuation_addition: dict,
) -> None:
    client = _client(tmp_path)
    first = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=initial_messages,
        tools=_live_probe_tools(),
    )
    assert len(first.tool_calls) == 1
    tool_call = first.tool_calls[0]
    original_turn = client._pending_turn
    assert original_turn is not None

    if continuation_addition["content"].startswith("[Game status]"):
        continuation_messages = [
            initial_messages[0],
            continuation_addition,
        ]
    else:
        continuation_messages = [*initial_messages, continuation_addition]
    continuation_messages.extend(
        [
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": "route-ready",
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                ],
            },
        ]
    )

    replay = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=continuation_messages,
        tools=_live_probe_tools(),
    )

    try:
        # A same-turn resume would have returned "Tool result received". A new
        # tool call proves the complete changed prompt went to a fresh process.
        assert replay.text is None
        assert len(replay.tool_calls) == 1
        assert original_turn.closed is True
        assert original_turn.rpc.process.poll() is not None
        assert client._pending_turn is not None
        assert client._pending_turn is not original_turn
    finally:
        client.close()


def test_client_close_terminates_a_pending_dynamic_turn(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[{"role": "user", "content": "Run the probe."}],
        tools=_live_probe_tools(),
    )
    assert result.tool_calls
    active = client._pending_turn
    assert active is not None
    assert active.rpc.process.poll() is None

    client.close()

    assert client._pending_turn is None
    assert active.closed is True
    assert active.rpc.process.poll() is not None


def test_stale_expiration_cannot_close_rearmed_pending_turn(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[{"role": "user", "content": "Run the probe."}],
        tools=_live_probe_tools(),
    )
    assert result.tool_calls
    active = client._pending_turn
    assert active is not None
    stale_generation = active.expiration_generation

    # Re-arming models a second dynamic tool on the same app-server turn.
    client._arm_pending_expiration(active)
    current_generation = active.expiration_generation
    assert current_generation == stale_generation + 1

    client._expire_pending(active, stale_generation)

    assert client._pending_turn is active
    assert active.closed is False
    assert active.rpc.process.poll() is None

    client._expire_pending(active, current_generation)

    assert client._pending_turn is None
    assert active.closed is True
    assert active.rpc.process.poll() is not None


@pytest.mark.parametrize("empty_mode", ["empty_message", "missing_message"])
def test_empty_same_turn_final_gets_one_fresh_replay(
    monkeypatch: pytest.MonkeyPatch,
    empty_mode: str,
) -> None:
    client = CodexAppServerClient("codex")
    active = object()
    replayed = CodexAppServerResult(text="Recovered.", tool_calls=[], usage={})
    replay_calls: list[dict] = []
    lifecycle: list[str] = []

    monkeypatch.setattr(client, "_resume_pending_turn", lambda messages: active)
    def wait_for_resumed_turn(current, retain_tool_turn):
        if empty_mode == "missing_message":
            raise _CodexAppServerNoFinalResponse("no final response")
        return CodexAppServerResult(
            text=None,
            tool_calls=[],
            usage={"total_tokens": 7},
        )

    monkeypatch.setattr(client, "_wait_for_turn", wait_for_resumed_turn)
    monkeypatch.setattr(client, "_close_turn", lambda current: lifecycle.append("closed"))

    def replay_once(**kwargs):
        lifecycle.append("replayed")
        replay_calls.append(kwargs)
        return replayed

    monkeypatch.setattr(client, "_generate_new", replay_once)
    messages = [{"role": "tool", "tool_call_id": "call-1", "content": "ready"}]

    result = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=messages,
        tools=_live_probe_tools(),
    )

    assert result is replayed
    assert len(replay_calls) == 1
    assert replay_calls[0]["messages"] is messages
    assert replay_calls[0]["retain_tool_turn"] is True
    assert lifecycle == ["closed", "replayed"]


@pytest.mark.skipif(
    os.environ.get("COVAS_LIVE_CODEX_TEST") != "1",
    reason="requires an explicit live ChatGPT/Codex smoke-test opt in",
)
def test_live_codex_app_server_dynamic_tool_bridge() -> None:
    result = CodexAppServerClient(
        os.environ.get("COVAS_CODEX_COMMAND", "codex"),
        timeout_seconds=120,
    ).generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[
            {"role": "system", "content": "Follow the user's tool request exactly."},
            {
                "role": "user",
                "content": "Call probe_action with value set to ok. Do not reply with text.",
            },
        ],
        tools=_live_probe_tools(),
    )

    assert result.text is None
    assert result.tool_calls
    assert result.tool_calls[0]["name"] == "probe_action"
    assert json.loads(result.tool_calls[0]["arguments"])["value"] == "ok"


@pytest.mark.skipif(
    os.environ.get("COVAS_LIVE_CODEX_TEST") != "1",
    reason="requires an explicit live ChatGPT/Codex smoke-test opt in",
)
def test_live_codex_app_server_replays_tool_result_to_final_text() -> None:
    client = CodexAppServerClient(
        os.environ.get("COVAS_CODEX_COMMAND", "codex"),
        timeout_seconds=120,
    )
    system_prompt = (
        "This is a deterministic integration test. If no probe_action result is "
        "present in the conversation, call probe_action exactly once with value ok "
        "and emit no text. If its result is present, call no tool and reply with "
        "exactly that result text."
    )
    user_prompt = "Run probe_action once, then report its returned result."

    first = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=_live_probe_tools(),
    )

    assert first.text is None
    assert len(first.tool_calls) == 1
    tool_call = first.tool_calls[0]
    assert tool_call["name"] == "probe_action"
    assert json.loads(tool_call["arguments"])["value"] == "ok"

    tool_result = "COVAS_RESULT_route-ready-7319"
    final = client.generate(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        text_verbosity="low",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            # PromptGenerator's legacy COVAS history can put the result before
            # its assistant call. _prepare_messages must repair that ordering.
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_call["name"],
                "content": tool_result,
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                ],
            },
        ],
        tools=_live_probe_tools(),
    )

    assert final.tool_calls == []
    assert tool_result in (final.text or "")
