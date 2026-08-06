from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PureWindowsPath
from queue import Empty, Queue
import shlex
import shutil
import subprocess
import tempfile
from threading import RLock, Thread, Timer
from time import monotonic
from typing import Any, Callable
import weakref


class CodexAppServerError(RuntimeError):
    """Raised when the managed Codex app-server provider cannot complete a call."""


class _CodexAppServerNoFinalResponse(CodexAppServerError):
    """Raised when a completed app-server turn contains no assistant response."""


@dataclass
class CodexAppServerResult:
    text: str | None
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]


def _model_dump_compatible(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for raw_part in content:
            part = _model_dump_compatible(raw_part)
            if isinstance(part, dict) and part.get("type") in {"text", "input_text", "output_text"}:
                chunks.append(str(part.get("text", "")))
            else:
                chunks.append(json.dumps(part, ensure_ascii=False, default=str))
        return "\n".join(chunk for chunk in chunks if chunk)
    return json.dumps(content, ensure_ascii=False, default=str)


def _split_command(command: str, platform_name: str | None = None) -> list[str]:
    command = command.strip()
    if not command:
        raise CodexAppServerError("Codex app-server command is empty.")

    platform_name = platform_name or os.name
    parts = shlex.split(command, posix=platform_name != "nt")
    if platform_name == "nt":
        parts = [
            part[1:-1]
            if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}
            else part
            for part in parts
        ]
    if not parts:
        raise CodexAppServerError("Codex app-server command is empty.")
    return parts


def _app_server_argv(
    command: str,
    *,
    platform_name: str | None = None,
    executable_resolver: Callable[[str], str | None] = shutil.which,
    command_processor: str | None = None,
    environment: dict[str, str] | None = None,
    path_exists: Callable[[str], bool] = os.path.isfile,
) -> list[str]:
    platform_name = platform_name or os.name
    argv = _split_command(command, platform_name)
    if "app-server" not in argv:
        argv.append("app-server")

    if platform_name != "nt":
        return argv

    environment = environment or dict(os.environ)
    argv[0] = _resolve_windows_executable(
        argv[0],
        executable_resolver=executable_resolver,
        environment=environment,
        path_exists=path_exists,
    )
    if PureWindowsPath(argv[0]).suffix.lower() not in {".cmd", ".bat"}:
        return argv

    # CreateProcess cannot execute a batch shim directly. npm/nvm installs the
    # Codex CLI as codex.cmd, so invoke that shim through the native command
    # processor while still passing a fixed argv (never shell=True).
    resolved_processor = command_processor or environment.get("COMSPEC") or "cmd.exe"
    return [resolved_processor, "/d", "/s", "/c", subprocess.list2cmdline(argv)]


def _resolve_windows_executable(
    executable: str,
    *,
    executable_resolver: Callable[[str], str | None],
    environment: dict[str, str],
    path_exists: Callable[[str], bool],
) -> str:
    resolved = executable_resolver(executable)
    candidates: list[str] = []

    if resolved:
        resolved_path = PureWindowsPath(resolved)
        if resolved_path.suffix.lower() == ".ps1":
            # PowerShell's command discovery often returns the npm .ps1 shim,
            # while Python needs the sibling cmd shim for redirected stdio.
            candidates.extend(
                [str(resolved_path.with_suffix(".cmd")), str(resolved_path.with_suffix(".bat"))]
            )
        else:
            return resolved

    executable_path = PureWindowsPath(executable)
    if executable_path.suffix:
        candidates.append(str(executable_path))
    else:
        for raw_directory in environment.get("PATH", "").split(";"):
            directory = raw_directory.strip().strip('"')
            if not directory:
                continue
            for suffix in (".cmd", ".bat", ".exe"):
                candidates.append(str(PureWindowsPath(directory) / f"{executable}{suffix}"))

        user_profile = environment.get("USERPROFILE")
        if user_profile:
            candidates.append(
                str(
                    PureWindowsPath(user_profile)
                    / "scoop"
                    / "apps"
                    / "nvm"
                    / "current"
                    / "nodejs"
                    / "nodejs"
                    / f"{executable}.cmd"
                )
            )
        appdata = environment.get("APPDATA")
        if appdata:
            candidates.append(str(PureWindowsPath(appdata) / "npm" / f"{executable}.cmd"))

    for candidate in candidates:
        if path_exists(candidate):
            return candidate
    return resolved or executable


def _tool_specs_for_prompt(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for raw_tool in tools:
        tool = _model_dump_compatible(raw_tool)
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = _model_dump_compatible(tool.get("function"))
        if not isinstance(function, dict) or not function.get("name"):
            continue
        specs.append(
            {
                "name": str(function["name"]),
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object"},
            }
        )
    return specs


class _JsonRpcProcess:
    def __init__(self, command: str, timeout_seconds: float):
        argv = _app_server_argv(command)

        creation_flags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            self.process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
        except (FileNotFoundError, OSError) as exc:
            raise CodexAppServerError(
                f"Unable to start Codex app-server with {command!r}. Install/update the Codex CLI or change the command in Advanced Settings."
            ) from exc

        self.timeout_seconds = max(float(timeout_seconds), 1.0)
        self.deadline = monotonic() + self.timeout_seconds
        self.messages: Queue[dict[str, Any] | BaseException | None] = Queue()
        self.stderr_lines: list[str] = []
        self._next_id = 1
        self._responses: dict[int, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._server_requests: list[dict[str, Any]] = []

        Thread(target=self._read_stdout, daemon=True).start()
        Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                line = line.strip()
                if line:
                    self.messages.put(json.loads(line))
        except BaseException as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            line = line.rstrip()
            if line:
                self.stderr_lines.append(line)
                del self.stderr_lines[:-20]

    def _write(self, payload: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise CodexAppServerError(self._exit_message())
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise CodexAppServerError(self._exit_message()) from exc

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        """Answer a server-initiated JSON-RPC request on the same connection."""
        self._write({"id": request_id, "result": result})

    def reset_deadline(self) -> None:
        self.deadline = monotonic() + self.timeout_seconds

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

        while request_id not in self._responses:
            self._pump_one()
        response = self._responses.pop(request_id)
        if response.get("error"):
            error = response["error"]
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise CodexAppServerError(f"Codex app-server {method} failed: {detail}")
        result = response.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def wait_for(self, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        for collection in (self._notifications, self._server_requests):
            for index, event in enumerate(collection):
                if predicate(event):
                    return collection.pop(index)
        while True:
            message = self._pump_one()
            if "method" in message and predicate(message):
                for collection in (self._notifications, self._server_requests):
                    for index, queued in enumerate(collection):
                        if queued is message:
                            collection.pop(index)
                            break
                return message

    def wait_for_optional(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Wait briefly for telemetry that may follow a paused tool request."""
        original_deadline = self.deadline
        self.deadline = min(original_deadline, monotonic() + max(0.0, timeout_seconds))
        try:
            return self.wait_for(predicate)
        except CodexAppServerError as exc:
            if " timed out after " in str(exc) and self.process.poll() is None:
                return None
            raise
        finally:
            self.deadline = original_deadline

    def _pump_one(self) -> dict[str, Any]:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise CodexAppServerError(
                f"Codex app-server timed out after {self.timeout_seconds:g} seconds."
            )
        try:
            message = self.messages.get(timeout=remaining)
        except Empty as exc:
            raise CodexAppServerError(
                f"Codex app-server timed out after {self.timeout_seconds:g} seconds."
            ) from exc
        if message is None:
            raise CodexAppServerError(self._exit_message())
        if isinstance(message, BaseException):
            raise CodexAppServerError(f"Invalid output from Codex app-server: {message}") from message
        if "id" in message and ("result" in message or "error" in message):
            response_id = message.get("id")
            if isinstance(response_id, int):
                self._responses[response_id] = message
        elif "id" in message and "method" in message:
            if message.get("method") == "item/tool/call":
                self._server_requests.append(message)
            else:
                # COVAS never grants app-server access to host/built-in actions.
                self._write(
                    {
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": f"COVAS does not expose app-server method {message.get('method')}",
                        },
                    }
                )
        elif "method" in message:
            self._notifications.append(message)
        return message

    def _exit_message(self) -> str:
        details = "\n".join(self.stderr_lines[-5:])
        suffix = f" Last output:\n{details}" if details else ""
        return f"Codex app-server exited before completing the request.{suffix}"

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


@dataclass
class _ActiveCodexTurn:
    rpc: _JsonRpcProcess
    temp_context: Any
    tool_specs: list[dict[str, Any]]
    usage: dict[str, int]
    prompt_fingerprints: tuple[str, ...]
    final_text: str | None = None
    pending_request_id: int | str | None = None
    pending_call_id: str | None = None
    pending_tool_name: str | None = None
    expiration_timer: Timer | None = None
    expiration_generation: int = 0
    closed: bool = False


class CodexAppServerClient:
    """ChatGPT OAuth client backed by the official Codex app-server.

    COVAS executes actions outside the model adapter. When app-server pauses a
    turn for a dynamic tool, keep that process alive until the matching COVAS
    tool result arrives on the next ``generate`` call. This preserves the same
    model turn (and its reasoning state) instead of reconstructing it unless the
    pending process has already expired.
    """

    def __init__(
        self,
        command: str,
        timeout_seconds: float = 120,
    ):
        self.command = command
        self.timeout_seconds = timeout_seconds
        self._lock = RLock()
        self._pending_turn: _ActiveCodexTurn | None = None

    def generate(
        self,
        *,
        model: str,
        reasoning_effort: str | None,
        text_verbosity: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> CodexAppServerResult:
        with self._lock:
            active = self._resume_pending_turn(messages)
            if active is not None:
                try:
                    try:
                        result = self._wait_for_turn(active, retain_tool_turn=True)
                    except _CodexAppServerNoFinalResponse:
                        result = CodexAppServerResult(text=None, tool_calls=[], usage={})
                finally:
                    if self._pending_turn is not active:
                        self._close_turn(active)

                if result.text is not None or result.tool_calls:
                    return result

                # A completed resumed turn can very rarely contain an empty
                # final agent message. Replay the already supplied COVAS call
                # and tool result once on a fresh ephemeral thread; never loop.
                return self._generate_new(
                    model=model,
                    reasoning_effort=reasoning_effort,
                    text_verbosity=text_verbosity,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    retain_tool_turn=self._pending_turn is None,
                )

            # Action-cache verification can issue an unrelated model call after
            # COVAS executes the requested action but before its ToolEvent is
            # rendered into the next prompt. Keep the real turn pending and make
            # that unrelated call one-shot so it cannot displace the continuation.
            return self._generate_new(
                model=model,
                reasoning_effort=reasoning_effort,
                text_verbosity=text_verbosity,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                retain_tool_turn=self._pending_turn is None,
            )

    def _generate_new(
        self,
        *,
        model: str,
        reasoning_effort: str | None,
        text_verbosity: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
        retain_tool_turn: bool,
    ) -> CodexAppServerResult:
        rpc = _JsonRpcProcess(self.command, self.timeout_seconds)
        temp_context: Any = None
        active: _ActiveCodexTurn | None = None
        try:
            rpc.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "covas-next",
                        "title": "COVAS:NEXT",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True, "requestAttestation": False},
                },
            )
            rpc.notify("initialized")

            account_result = rpc.request("account/read", {"refreshToken": False})
            account = account_result.get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise CodexAppServerError(
                    "ChatGPT OAuth is not active in the configured Codex CLI. Sign in with `codex login`, then retry. COVAS never reads or copies Codex token files."
                )

            system_instructions, developer_instructions, history, turn_text = self._prepare_messages(messages)
            tool_specs = _tool_specs_for_prompt(tools or [])
            developer_instructions = self._developer_instructions(
                developer_instructions,
                tool_specs,
                tool_choice,
            )

            config: dict[str, Any] = {
                "web_search": "disabled",
                "mcp_servers": {},
                "agents": {"enabled": False},
                "apps": {"_default": {"enabled": False}},
                "include_permissions_instructions": False,
                "include_apps_instructions": False,
                "include_collaboration_mode_instructions": False,
                "include_skill_instructions": False,
                "include_environment_context": False,
                "orchestrator_skills_enabled": False,
                "orchestrator_mcp_enabled": False,
                "features": {
                    "apps": False,
                    "goals": False,
                    "hooks": False,
                    "multi_agent": False,
                    "shell_tool": False,
                    "unified_exec": False,
                },
                "history": {"persistence": "none"},
            }
            if text_verbosity and text_verbosity != "default":
                config["model_verbosity"] = text_verbosity

            temp_context = tempfile.TemporaryDirectory(prefix="covas-codex-")
            temp_cwd = temp_context.name
            thread_params: dict[str, Any] = {
                "model": model,
                "cwd": str(Path(temp_cwd).resolve()),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "config": config,
                "serviceName": "covas-next",
                "baseInstructions": system_instructions,
                "developerInstructions": developer_instructions,
                "ephemeral": True,
            }
            if tool_specs:
                thread_params["dynamicTools"] = [
                    {
                        "type": "function",
                        "name": spec["name"],
                        "description": spec["description"],
                        "inputSchema": spec["parameters"],
                    }
                    for spec in tool_specs
                ]
            start_result = rpc.request("thread/start", thread_params)
            thread = start_result.get("thread")
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str) or not thread_id:
                raise CodexAppServerError("Codex app-server did not return a thread id.")

            if history:
                rpc.request("thread/inject_items", {"threadId": thread_id, "items": history})

            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": turn_text}],
                "model": model,
            }
            if reasoning_effort and reasoning_effort != "default":
                turn_params["effort"] = reasoning_effort
            rpc.request("turn/start", turn_params)

            active = _ActiveCodexTurn(
                rpc=rpc,
                temp_context=temp_context,
                tool_specs=tool_specs,
                usage={},
                prompt_fingerprints=self._message_fingerprints(messages),
            )
            return self._wait_for_turn(active, retain_tool_turn=retain_tool_turn)
        finally:
            if active is None:
                rpc.close()
                if temp_context is not None:
                    temp_context.cleanup()
            elif self._pending_turn is not active:
                self._close_turn(active)

    def _wait_for_turn(
        self,
        active: _ActiveCodexTurn,
        *,
        retain_tool_turn: bool,
    ) -> CodexAppServerResult:
        rpc = active.rpc
        while True:
            notification = rpc.wait_for(
                lambda item: item.get("method")
                in {
                    "item/completed",
                    "thread/tokenUsage/updated",
                    "turn/completed",
                    "error",
                    "item/tool/call",
                }
            )
            method = notification.get("method")
            params = notification.get("params")
            params = params if isinstance(params, dict) else {}
            if method == "item/completed":
                item = params.get("item")
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    phase = item.get("phase")
                    if phase in {None, "final_answer"}:
                        active.final_text = str(item.get("text") or "")
            elif method == "item/tool/call":
                tool_name = params.get("tool")
                arguments = params.get("arguments")
                call_id = params.get("callId")
                request_id = notification.get("id")
                allowed_tools = {spec["name"] for spec in active.tool_specs}
                if not isinstance(tool_name, str) or tool_name not in allowed_tools:
                    raise CodexAppServerError(
                        f"Codex app-server requested unknown action: {tool_name!r}."
                    )
                if not isinstance(arguments, dict):
                    raise CodexAppServerError(
                        f"Arguments for action {tool_name!r} must be a JSON object."
                    )
                if not isinstance(call_id, str) or not call_id:
                    raise CodexAppServerError(
                        f"Codex app-server omitted the call id for action {tool_name!r}."
                    )
                if isinstance(request_id, bool) or not isinstance(request_id, (int, str)):
                    raise CodexAppServerError(
                        f"Codex app-server omitted the request id for action {tool_name!r}."
                    )
                # The turn pauses on the dynamic tool request, but its token
                # usage notification is often written immediately afterwards.
                usage_notification = rpc.wait_for_optional(
                    lambda item: item.get("method") == "thread/tokenUsage/updated",
                    0.2,
                )
                if usage_notification is not None:
                    usage_params = usage_notification.get("params")
                    self._record_usage(
                        active,
                        usage_params if isinstance(usage_params, dict) else {},
                    )
                if retain_tool_turn:
                    active.pending_request_id = request_id
                    active.pending_call_id = call_id
                    active.pending_tool_name = tool_name
                    self._pending_turn = active
                    self._arm_pending_expiration(active)
                return CodexAppServerResult(
                    text=None,
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": tool_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        }
                    ],
                    usage=dict(active.usage),
                )
            elif method == "thread/tokenUsage/updated":
                self._record_usage(active, params)
            elif method == "error":
                raise CodexAppServerError(
                    str(params.get("message") or "Codex app-server reported an error.")
                )
            elif method == "turn/completed":
                turn = params.get("turn")
                if isinstance(turn, dict) and turn.get("status") == "failed":
                    error = turn.get("error")
                    detail = error.get("message") if isinstance(error, dict) else error
                    raise CodexAppServerError(f"Codex app-server turn failed: {detail}")
                break

        if active.final_text is None:
            raise _CodexAppServerNoFinalResponse(
                "Codex app-server completed without a final response."
            )
        return CodexAppServerResult(
            text=active.final_text or None,
            tool_calls=[],
            usage=dict(active.usage),
        )

    @staticmethod
    def _record_usage(active: _ActiveCodexTurn, notification_params: dict[str, Any]) -> None:
        token_usage = notification_params.get("tokenUsage")
        last = token_usage.get("last") if isinstance(token_usage, dict) else None
        if isinstance(last, dict):
            active.usage = {
                "input_tokens": int(last.get("inputTokens") or 0),
                "cached_tokens": int(last.get("cachedInputTokens") or 0),
                "output_tokens": int(last.get("outputTokens") or 0),
                "reasoning_tokens": int(last.get("reasoningOutputTokens") or 0),
                "total_tokens": int(last.get("totalTokens") or 0),
            }

    def _resume_pending_turn(
        self,
        messages: list[dict[str, Any]],
    ) -> _ActiveCodexTurn | None:
        active = self._pending_turn
        if active is None or active.pending_call_id is None:
            return None

        found, output, prompt_unchanged = self._find_unmodified_tool_result(
            messages,
            active,
        )
        if not prompt_unchanged:
            # A new commander utterance, game event, or changed live-status
            # message must be visible to the model. Abandon the paused turn so
            # generate() replays the complete current COVAS prompt instead of
            # resuming reasoning that predates that information.
            self._pending_turn = None
            self._close_turn(active)
            return None
        if not found:
            return None

        self._pending_turn = None
        if active.expiration_timer is not None:
            active.expiration_timer.cancel()
            active.expiration_timer = None

        request_id = active.pending_request_id
        if request_id is None:
            self._close_turn(active)
            return None

        active.rpc.reset_deadline()
        try:
            active.rpc.respond(
                request_id,
                {
                    "contentItems": [{"type": "inputText", "text": output}],
                    "success": not output.lstrip().upper().startswith("ERROR:"),
                },
            )
        except CodexAppServerError:
            # The normal COVAS prompt still contains the call and result, so a
            # fresh ephemeral thread remains a safe compatibility fallback.
            self._close_turn(active)
            return None

        active.pending_request_id = None
        active.pending_call_id = None
        active.pending_tool_name = None
        # A resumed turn may request another dynamic tool. Its continuation
        # baseline includes the call/result that was just accepted here.
        active.prompt_fingerprints = self._message_fingerprints(messages)
        return active

    @staticmethod
    def _message_fingerprints(messages: list[dict[str, Any]]) -> tuple[str, ...]:
        return tuple(
            json.dumps(
                _model_dump_compatible(raw_message),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for raw_message in messages
        )

    @classmethod
    def _find_unmodified_tool_result(
        cls,
        messages: list[dict[str, Any]],
        active: _ActiveCodexTurn,
    ) -> tuple[bool, str, bool]:
        call_id = active.pending_call_id
        if call_id is None:
            return False, "", False

        result_indices: list[int] = []
        assistant_indices: list[int] = []
        output = ""
        for index, raw_message in enumerate(messages):
            message = _model_dump_compatible(raw_message)
            if not isinstance(message, dict):
                continue
            if message.get("role") == "tool":
                message_call_id = message.get("tool_call_id") or message.get("call_id")
                if str(message_call_id or "") == call_id:
                    result_indices.append(index)
                    output = _stringify_content(message.get("content"))
            elif cls._is_expected_assistant_tool_call(
                message,
                call_id,
                active.pending_tool_name,
            ):
                assistant_indices.append(index)

        # One tool result is the only required addition. COVAS also normally
        # records the corresponding assistant tool-call envelope; app-server
        # already owns that call, so the envelope is optional but may occur once.
        if len(result_indices) > 1 or len(assistant_indices) > 1:
            return bool(result_indices), output, False

        expected_indices = set(result_indices + assistant_indices)
        remaining_messages = [
            raw_message
            for index, raw_message in enumerate(messages)
            if index not in expected_indices
        ]
        prompt_unchanged = (
            cls._message_fingerprints(remaining_messages) == active.prompt_fingerprints
        )
        return len(result_indices) == 1, output, prompt_unchanged

    @staticmethod
    def _is_expected_assistant_tool_call(
        message: dict[str, Any],
        call_id: str,
        tool_name: str | None,
    ) -> bool:
        if message.get("role") != "assistant":
            return False
        if _stringify_content(message.get("content")).strip():
            return False
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list) or len(raw_calls) != 1:
            return False
        call = _model_dump_compatible(raw_calls[0])
        if not isinstance(call, dict):
            return False
        message_call_id = call.get("id") or call.get("call_id")
        if str(message_call_id or "") != call_id:
            return False
        function = _model_dump_compatible(call.get("function"))
        if not isinstance(function, dict):
            return False
        return tool_name is None or str(function.get("name") or "") == tool_name

    def _arm_pending_expiration(self, active: _ActiveCodexTurn) -> None:
        if active.expiration_timer is not None:
            active.expiration_timer.cancel()
        active.expiration_generation += 1
        expiration_generation = active.expiration_generation
        active.rpc.reset_deadline()
        client_ref = weakref.ref(self)

        def expire() -> None:
            client = client_ref()
            if client is not None:
                client._expire_pending(active, expiration_generation)

        timer = Timer(max(float(self.timeout_seconds), 1.0), expire)
        timer.daemon = True
        active.expiration_timer = timer
        timer.start()

    def _expire_pending(
        self,
        active: _ActiveCodexTurn,
        expiration_generation: int,
    ) -> None:
        with self._lock:
            if (
                self._pending_turn is active
                and active.expiration_generation == expiration_generation
            ):
                self._pending_turn = None
                self._close_turn(active)

    @staticmethod
    def _close_turn(active: _ActiveCodexTurn) -> None:
        if active.closed:
            return
        active.closed = True
        if active.expiration_timer is not None:
            active.expiration_timer.cancel()
            active.expiration_timer = None
        # On Windows app-server keeps its cwd open until the child exits.
        active.rpc.close()
        active.temp_context.cleanup()

    def close(self) -> None:
        with self._lock:
            active = self._pending_turn
            self._pending_turn = None
            if active is not None:
                self._close_turn(active)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _prepare_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, str, list[dict[str, Any]], str]:
        system_parts: list[str] = []
        developer_parts: list[str] = []
        conversational: list[dict[str, Any]] = []

        for raw_message in messages:
            message = _model_dump_compatible(raw_message)
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "system":
                system_parts.append(_stringify_content(message.get("content")))
            elif role == "developer":
                developer_parts.append(_stringify_content(message.get("content")))
            else:
                conversational.append(message)

        turn_text = "Continue the COVAS conversation and produce the next assistant result."
        if conversational and conversational[-1].get("role") == "user":
            last_user = conversational.pop()
            turn_text = _stringify_content(last_user.get("content")) or turn_text

        history: list[dict[str, Any]] = []
        known_call_ids: set[str] = set()
        deferred_outputs: dict[str, list[dict[str, Any]]] = {}
        for message in conversational:
            role = message.get("role")
            content = _stringify_content(message.get("content"))
            if role == "user" and content:
                history.append(
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": content}]}
                )
            elif role == "assistant":
                if content:
                    history.append(
                        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]}
                    )
                for raw_call in message.get("tool_calls") or []:
                    call = _model_dump_compatible(raw_call)
                    function = _model_dump_compatible(call.get("function")) if isinstance(call, dict) else None
                    if not isinstance(call, dict) or not isinstance(function, dict):
                        continue
                    history.append(
                        {
                            "type": "function_call",
                            "call_id": str(call.get("id") or call.get("call_id") or ""),
                            "name": str(function.get("name") or ""),
                            "arguments": str(function.get("arguments") or "{}"),
                        }
                    )
                    call_id = str(call.get("id") or call.get("call_id") or "")
                    if call_id:
                        known_call_ids.add(call_id)
                        history.extend(deferred_outputs.pop(call_id, []))
            elif role == "tool":
                call_id = message.get("tool_call_id") or message.get("call_id")
                if call_id:
                    output = {
                        "type": "function_call_output",
                        "call_id": str(call_id),
                        "output": content,
                    }
                    if str(call_id) in known_call_ids:
                        history.append(output)
                    else:
                        deferred_outputs.setdefault(str(call_id), []).append(output)

        for call_id, outputs in deferred_outputs.items():
            for output in outputs:
                history.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"[Tool result for {call_id}] {output.get('output', '')}",
                            }
                        ],
                    }
                )

        system = "\n\n".join(part for part in system_parts if part).strip()
        if not system:
            system = "You are the configured cockpit assistant in COVAS:NEXT."
        return system, "\n\n".join(developer_parts), history, turn_text

    def _developer_instructions(
        self,
        existing: str,
        tool_specs: list[dict[str, Any]],
        tool_choice: Any,
    ) -> str:
        instructions = [
            "You are running only as COVAS:NEXT's language-model backend.",
            "Follow the supplied COVAS system instructions and conversation. Return only the assistant reply or call a provided COVAS dynamic tool.",
            "Do not use shell, filesystem, web search, apps, MCP, skills, plans, subagents, or any Codex built-in tool.",
            "When an action is needed, call only a provided COVAS dynamic tool. Do not invent action names.",
        ]
        if existing:
            instructions.append(existing)
        if not tool_specs:
            instructions.append("No COVAS actions are available for this turn; reply with text only.")
        if tool_choice:
            instructions.append(
                "The caller supplied this tool-choice constraint: "
                + json.dumps(_model_dump_compatible(tool_choice), ensure_ascii=False, default=str)
            )
        return "\n\n".join(instructions)
