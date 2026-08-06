from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_user_asset_protocol_supports_cross_origin_fetch() -> None:
    electron = _source("electron/index.js")
    scheme_start = electron.index("scheme: 'user-asset'")
    scheme_end = electron.index("}\n]);", scheme_start)
    user_asset_scheme = electron[scheme_start:scheme_end]

    assert "supportFetchAPI: true" in user_asset_scheme
    assert "corsEnabled: true" in user_asset_scheme


def test_managed_avatars_stream_but_legacy_external_paths_keep_exact_ipc_fallback() -> None:
    electron = _source("electron/index.js")
    preload = _source("electron/preload.js")
    avatar = _source("ui/src/app/services/avatar.service.ts")

    assert "get_user_asset_file_info" in electron
    assert "getFileInfo: (opts) => ipcRenderer.invoke('get_user_asset_file_info', opts)" in preload
    assert "searchParams.get('path')" in electron
    assert "await assertUserAssetPath(exactPath)" in electron
    assert "fileInfo.managed" in avatar
    assert "getLegacyExternalAvatar(fileInfo.path" in avatar
    assert "URL.createObjectURL(blob)" in avatar
    assert "?path=${encodeURIComponent(reference)}" in avatar


def test_restart_process_has_one_stop_cycle() -> None:
    tauri = _source("ui/src/app/services/tauri.service.ts")
    restart_start = tauri.index("public async restart_process")
    restart_end = tauri.index("public async send_start_signal", restart_start)
    restart_body = tauri[restart_start:restart_end]

    assert restart_body.count("await this.stopExe()") == 1
    assert "await this.startExe()" in restart_body
    assert "await this.runExe()" not in restart_body


def test_stop_failure_and_manual_tabs_return_ui_to_interactive_state() -> None:
    tauri = _source("ui/src/app/services/tauri.service.ts")
    main_view = _source("ui/src/app/main-view/main-view.component.ts")
    template = _source("ui/src/app/main-view/main-view.component.html")

    stop_start = tauri.index("private async stopExe")
    stop_end = tauri.index("public async restart_process", stop_start)
    assert 'this.runModeSubject.next("error")' in tauri[stop_start:stop_end]
    assert "this.isLoading = false" in main_view
    assert '[(selectedIndex)]="selectedTabIndex"' in template


def test_non_kgbfoam_warning_settings_use_normal_persistent_config_path() -> None:
    config_service = _source("ui/src/app/services/config.service.ts")
    actions_template = _source(
        "ui/src/app/components/actions-settings/actions-settings.component.html"
    )
    actions_component = _source(
        "ui/src/app/components/actions-settings/actions-settings.component.ts"
    )

    for setting in (
        "qol_non_kgbfoam_jump_warning",
        "qol_non_kgbfoam_unknown_warning",
    ):
        assert f"{setting}: boolean" in config_service
        assert f'onConfigChange({{{setting}: $event}})' in actions_template
    assert "await this.configService.changeConfig(partialConfig)" in actions_component
    assert '[disabled]="!config.qol_non_kgbfoam_jump_warning"' in actions_template


def test_non_kgbfoam_warning_uses_tts_without_llm_or_navigation_actions() -> None:
    chat = _source("src/Chat.py")
    handler_start = chat.index("def _handle_non_kgbfoam_jump_warning")
    handler_end = chat.index("\n    def on_event", handler_start)
    handler = chat[handler_start:handler_end]

    assert "self.tts.say(" in handler
    assert "_get_tts_postprocessing_layers" in handler
    for forbidden in (
        "llmModel",
        ".generate(",
        "web_search",
        "plotToTarget",
        "target_next_system_in_route",
        "set_speed",
    ):
        assert forbidden not in handler
