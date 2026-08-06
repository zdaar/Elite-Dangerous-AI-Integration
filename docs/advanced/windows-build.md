# Reproducible Windows build

This recipe builds both the Python backend and the Electron application from a clean checkout. It does not modify an installed COVAS:NEXT copy.

## Prerequisites

- Windows 10 or 11
- Git
- Python 3.12 (64-bit)
- Node.js LTS with npm
- PowerShell 7 or Windows PowerShell 5.1

Use a short checkout path when possible. PyInstaller and npm both create deeply nested paths.

## Install dependencies

Open PowerShell in the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
npm ci
npm --prefix ui ci
```

## Run checks

```powershell
python -m pytest --timeout 10 test -v
npm --prefix ui run build
```

## One-command release build

The fork includes a repeatable release script. From PowerShell in the repository root:

```powershell
.\scripts\build-windows-release.ps1
```

It installs locked dependencies, runs the Python regression suite, rebuilds the
PyInstaller backend, builds the Angular UI, creates `dist\win-unpacked`, and packages
the MSI. For an already-provisioned checkout, use `-SkipInstall`; use `-SkipMsi` while
iterating locally. `-SkipInstall` requires Windows-native npm dependencies. If the
checkout was last provisioned from WSL/Linux, run once without `-SkipInstall` so
Angular receives the Windows `esbuild` binary. The script rejects that mixed-platform
state before packaging.

Each release pass recreates `dist\win-unpacked` instead of updating it in place. This
prevents retired resources, local backup files, or an old `app.asar` from leaking into
the next package.

The packaged application also carries the fork's managed plugins and synchronizes them
to `%APPDATA%\com.covas-next.ui\plugins` before the backend starts. This keeps the
exobiology tools in step with the executable after an install or update.

The verified Elite guide is packaged separately and synchronized to
`%APPDATA%\com.covas-next.ui\managed-guides\elite`. It contains the tracked
`guides\elite` Markdown tree used by `lookup_elite_guide`; it does not read or modify
character profiles or `config.json`. Set `COVAS_ELITE_GUIDE_PATH` before launching to
use a different guide tree. An explicit override takes precedence over the managed copy.

## Build the Python backend

```powershell
python -m PyInstaller --noconfirm --clean Chat.spec
```

The standalone backend is written to `dist\Chat\Chat.exe`. Keep the complete `dist\Chat` directory together; the executable depends on its `_internal` directory.

## Build the complete application

```powershell
npm run build:ui
npm run package:dir
```

The unpacked Windows application is written under `dist\win-unpacked`. To create the MSI as well:

```powershell
npm run package:msi
```

## Local multilingual TTS

The fork includes first-class `Chatterbox (Local OpenAI API)` and `Qwen3-TTS (Local OpenAI API)` providers under **Settings → Advanced → TTS / Speaker Settings**.

For either provider:

1. Enter the server's OpenAI-compatible `/v1` endpoint.
2. Select English or French. The same value is persisted to STT language.
3. Leave **Append language to model name** enabled when the server routes models such as `chatterbox-fr` or `qwen3-tts-en`.
4. Enable **Warm TTS model** for on-demand containers. COVAS:NEXT synthesizes and discards a short startup phrase so the first spoken response is warm.
5. Put accent, tone, and delivery requirements in **Voice Tone Instructions**. These are stored per character.

For audio diagnostics, enable **Capture latest raw and processed speech**. Captures are written to:

```text
%APPDATA%\com.covas-next.ui\debug-audio\
```

The option is disabled by default to avoid retaining speech unnecessarily.

## Installing a locally built backend for testing

Close COVAS:NEXT before replacing backend files. Back up the existing `resources\Chat` directory, then replace it with the complete newly built `dist\Chat` directory. Do not replace only `Chat.exe`; mixed executable and `_internal` versions are not supported.
