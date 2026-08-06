from pathlib import Path
import json
import os
import sys

import pytest

from src.lib.CodexAppServer import CodexAppServerClient, _app_server_argv


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
        tools=[
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
        ],
    )

    assert result.text is None
    assert result.tool_calls
    assert result.tool_calls[0]["name"] == "probe_action"
    assert json.loads(result.tool_calls[0]["arguments"])["value"] == "ok"
