# OpenAI reasoning models and ChatGPT OAuth

COVAS:NEXT supports two OpenAI LLM transports:

- **OpenAI** uses an OpenAI API key and the Responses API.
- **OpenAI (ChatGPT OAuth via Codex)** uses the ChatGPT account managed by the
  official Codex CLI app-server. COVAS does not read, copy, export, or refresh
  Codex token files.

## Recommended COVAS profile

For a responsive tool-using assistant, start with:

- Model: `gpt-5.6-terra`
- Reasoning effort: `low`
- Text verbosity: `low`

`gpt-5.6-sol` is available for harder quality-first tasks, while
`gpt-5.6-luna` is the lower-cost, higher-volume option. GPT-5.6 supports
`none`, `low`, `medium`, `high`, `xhigh`, and `max` reasoning effort.

The direct API transport omits `temperature` for GPT-5 and o-series models so
reasoning requests do not send incompatible sampling parameters. Other model
families still receive the configured temperature.

## ChatGPT OAuth setup

1. Install Codex CLI 0.146.1 or newer.
2. Run `codex login` and complete the managed ChatGPT sign-in.
3. In Advanced Settings, choose **OpenAI (ChatGPT OAuth via Codex)** for the
   main LLM and, if wanted, the agent LLM.
4. Keep the Codex command as `codex`, or set an explicit command if Codex is not
   on the application PATH.

On Windows, COVAS resolves npm/NVM `codex.cmd` shims, including the common
Scoop NVM and `%APPDATA%\npm` locations. An explicit native `codex.cmd` path
can also be entered.

The ChatGPT OAuth provider starts an ephemeral, read-only app-server thread for
each independent COVAS request. Shell, filesystem, web, app, MCP, skill, and
multi-agent host tools are disabled. Only COVAS actions are exposed through
app-server `dynamicTools`. When the model selects one, COVAS executes it and
returns the result to the same app-server turn so the model retains its current
reasoning context. If that continuation exceptionally returns no assistant
text, COVAS performs one bounded replay from the recorded call and result.

The legacy COVAS action cache is bypassed for this provider. Terra therefore
does not make a second verification request after every new tool call; the
deterministic routing guard and the live tool result remain authoritative.

To verify the complete OAuth path after updating Codex CLI, run the opt-in live
smoke test from a Windows Python environment:

```powershell
$env:COVAS_LIVE_CODEX_TEST = '1'
python -m pytest test/lib/test_CodexAppServer.py -k replays_tool_result_to_final_text -v
```

## Boundaries

- ChatGPT OAuth covers the app-server model call only. It is not an OpenAI API
  key and cannot authenticate embeddings, speech, or other public API clients.
  Selecting the OAuth main provider disables OpenAI embeddings only when they
  do not have their own explicit embedding API key. Independently configured
  OpenAI, Google, custom, and local embeddings are preserved.
- The Codex CLI remains an external runtime dependency and must already have a
  managed ChatGPT login. The first version does not embed an OAuth login button
  inside COVAS.
- ChatGPT subscription limits and model availability still apply to the logged
  in account.
- Codex app-server dynamic tools are experimental. This integration is tested
  against Codex CLI 0.146.1; rerun the live tool-loop smoke test after a Codex
  CLI upgrade.

Official references:

- [Codex app-server](https://developers.openai.com/codex/app-server)
- [Codex authentication](https://developers.openai.com/codex/auth)
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
