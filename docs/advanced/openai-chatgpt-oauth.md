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
each COVAS model call. Shell, filesystem, web, app, MCP, skill, and multi-agent
host tools are disabled. Only COVAS actions are exposed through app-server
`dynamicTools`; COVAS executes the selected action and replays its result in
the next model call.

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

Official references:

- [Codex app-server](https://developers.openai.com/codex/app-server)
- [Codex authentication](https://developers.openai.com/codex/auth)
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
