import ast
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.lib.Config import (
    default_allowed_actions,
    merge_config_data,
    migrate,
    migrate_allowed_actions,
    update_config,
)


def test_migrate_empty_allowed_actions_enables_all_current_actions() -> None:
    migrated = migrate({"config_version": 18, "allowed_actions": []})

    assert migrated["config_version"] == 23
    assert migrated["allowed_actions"] == default_allowed_actions
    assert all(migrated["allowed_actions"].values())


def test_migrate_restrictive_allowed_actions_preserves_selection() -> None:
    migrated = migrate({
        "config_version": 18,
        "allowed_actions": ["fireWeapons", "setSpeed"],
    })

    assert migrated["allowed_actions"]["fireWeapons"] is True
    assert migrated["allowed_actions"]["setSpeed"] is True
    assert migrated["allowed_actions"]["textMessage"] is False
    assert set(migrated["allowed_actions"]) == set(default_allowed_actions)


def test_migrate_version_17_enables_plot_to_target_before_map_conversion() -> None:
    migrated = migrate({
        "config_version": 17,
        "allowed_actions": ["fireWeapons"],
    })

    assert migrated["allowed_actions"]["fireWeapons"] is True
    assert migrated["allowed_actions"]["plotToTarget"] is True
    assert migrated["allowed_actions"]["setSpeed"] is False


@pytest.mark.parametrize("legacy_value", [None, "invalid", 123])
def test_invalid_legacy_allowed_actions_preserves_allow_all_behavior(
    legacy_value: object,
) -> None:
    assert migrate_allowed_actions(legacy_value) == default_allowed_actions


def test_action_map_merge_adds_new_defaults_and_preserves_user_values() -> None:
    defaults = {
        "allowed_actions": {
            "existingAction": True,
            "newEnabledAction": True,
            "newDisabledAction": False,
        }
    }
    user = {"allowed_actions": {"existingAction": False}}

    assert merge_config_data(defaults, user) == {
        "allowed_actions": {
            "existingAction": False,
            "newEnabledAction": True,
            "newDisabledAction": False,
        }
    }


def test_legacy_backup_update_runs_full_action_migration(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lib.Config.emit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.lib.Config.save_config",
        lambda config: None,
    )
    current = {
        "config_version": 21,
        "allowed_actions": default_allowed_actions.copy(),
    }
    legacy_backup = {
        "config_version": 17,
        "allowed_actions": ["fireWeapons"],
    }

    updated = update_config(current, legacy_backup)  # type: ignore[arg-type]

    assert updated["config_version"] == 23
    assert updated["allowed_actions"]["fireWeapons"] is True
    assert updated["allowed_actions"]["plotToTarget"] is True
    assert updated["allowed_actions"]["setSpeed"] is False


def test_migrate_adds_local_tts_settings_and_preserves_stt_language() -> None:
    migrated = migrate({
        "config_version": 19,
        "allowed_actions": default_allowed_actions.copy(),
        "stt_language": "fr",
    })

    assert migrated["config_version"] == 23
    assert migrated["tts_language"] == "fr"
    assert migrated["tts_chatterbox_endpoint"] == "http://localhost:8004/v1"
    assert migrated["tts_qwen3_endpoint"] == "http://localhost:8005/v1"
    assert migrated["tts_append_language_to_model"] is True
    assert migrated["tts_warmup_enabled"] is False
    assert migrated["tts_debug_capture_enabled"] is False


def test_migrate_adds_reasoning_output_and_codex_transport_settings_without_changing_provider() -> None:
    migrated = migrate({
        "config_version": 20,
        "llm_provider": "custom",
        "llm_model_name": "deepseek-chat",
        "agent_llm_provider": "custom",
        "agent_llm_model_name": "deepseek-chat",
    })

    assert migrated["config_version"] == 23
    assert migrated["llm_provider"] == "custom"
    assert migrated["llm_model_name"] == "deepseek-chat"
    assert migrated["agent_llm_provider"] == "custom"
    assert migrated["agent_llm_model_name"] == "deepseek-chat"
    assert migrated["llm_text_verbosity"] == "low"
    assert migrated["agent_llm_text_verbosity"] == "low"
    assert migrated["codex_app_server_command"] == "codex"
    assert migrated["codex_app_server_timeout"] == 120


def test_migrate_enables_requested_non_kgbfoam_warning_without_touching_profile() -> None:
    legacy = {
        "config_version": 21,
        "commander_name": "CMDR Test",
        "cn_autostart": True,
        "characters": [{"name": "Nova", "avatar": "nova.png"}],
        "tts_provider": "chatterbox-local",
        "stt_provider": "none",
        "plugin_settings": {"exobiology": {"queue": ["Sample A"]}},
    }

    migrated = migrate(legacy)

    assert migrated["config_version"] == 23
    assert migrated["qol_non_kgbfoam_jump_warning"] is True
    assert migrated["qol_non_kgbfoam_unknown_warning"] is False
    assert migrated["commander_name"] == "CMDR Test"
    assert migrated["cn_autostart"] is True
    assert migrated["characters"] == [{"name": "Nova", "avatar": "nova.png"}]
    assert migrated["tts_provider"] == "chatterbox-local"
    assert migrated["stt_provider"] == "none"
    assert migrated["plugin_settings"] == {"exobiology": {"queue": ["Sample A"]}}


def test_close_star_route_safety_migration_preserves_all_existing_state() -> None:
    legacy = {
        "config_version": 22,
        "commander_name": "CMDR Test",
        "characters": [{"name": "Nova", "tts_voice": "custom"}],
        "llm_provider": "custom",
        "tts_provider": "qwen3-tts-local",
        "cn_autostart": True,
        "plugin_settings": {"exobiology": {"index": 4, "targets": ["A", "B"]}},
    }

    migrated = migrate(legacy)

    assert migrated["config_version"] == 23
    assert migrated["route_safety_close_star_enabled"] is True
    assert migrated["route_safety_cancel_dangerous_charge"] is True
    assert migrated["route_safety_unknown_system_policy"] == "allow"
    assert migrated["route_safety_max_surface_gap_ratio"] == 1.0
    for key in (
        "commander_name",
        "characters",
        "llm_provider",
        "tts_provider",
        "cn_autostart",
        "plugin_settings",
    ):
        assert migrated[key] == legacy[key]


@pytest.mark.parametrize("embedding_provider", ["google-ai-studio", "custom", "local-ai-server"])
def test_chatgpt_oauth_preserves_independent_embedding_provider(
    monkeypatch,
    embedding_provider: str,
) -> None:
    monkeypatch.setattr("src.lib.Config.emit_message", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.lib.Config.save_config", lambda config: None)
    current = {
        "config_version": 21,
        "llm_provider": "custom",
        "embedding_provider": embedding_provider,
    }

    updated = update_config(current, {"llm_provider": "openai-chatgpt"})  # type: ignore[arg-type]

    assert updated["llm_provider"] == "openai-chatgpt"
    assert updated["embedding_provider"] == embedding_provider


def test_chatgpt_oauth_disables_public_openai_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("src.lib.Config.emit_message", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.lib.Config.save_config", lambda config: None)
    current = {
        "config_version": 21,
        "llm_provider": "openai",
        "embedding_provider": "openai",
        "embedding_api_key": "",
    }

    updated = update_config(current, {"llm_provider": "openai-chatgpt"})  # type: ignore[arg-type]

    assert updated["embedding_provider"] == "none"


def test_chatgpt_oauth_preserves_openai_embeddings_with_an_independent_key(monkeypatch) -> None:
    monkeypatch.setattr("src.lib.Config.emit_message", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.lib.Config.save_config", lambda config: None)
    current = {
        "config_version": 21,
        "llm_provider": "custom",
        "embedding_provider": "openai",
        "embedding_api_key": "sk-independent-embedding",
    }

    updated = update_config(current, {"llm_provider": "openai-chatgpt"})  # type: ignore[arg-type]

    assert updated["embedding_provider"] == "openai"
    assert updated["embedding_api_key"] == "sk-independent-embedding"


def test_action_defaults_match_registered_permissions() -> None:
    actions_source = (
        ROOT_DIR / "src" / "lib" / "actions" / "Actions.py"
    ).read_text(encoding="utf-8")
    registered_permissions = {
        keyword.value.value
        for node in ast.walk(ast.parse(actions_source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "registerAction"
        for keyword in node.keywords
        if keyword.arg == "permission"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }

    assert set(default_allowed_actions) == registered_permissions
