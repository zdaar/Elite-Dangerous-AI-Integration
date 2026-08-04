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

