import copy
import sys
from time import sleep
from typing import Any, cast, final
import os
import threading
import json
import io
import traceback
from datetime import datetime
from pathlib import Path
import yaml

from EDMesg.CovasNext import (
    ExternalChatNotification,
    ExternalBackgroundChatNotification,
)
from lib.Models import (
    create_llm_model,
    LLMModel,
    create_embedding_model,
    EmbeddingModel,
    create_stt_model,
    STTModel,
    create_tts_model,
    TTSModel,
)

from lib.PluginHelper import PluginHelper
from lib.Config import (
    Config,
    assign_ptt,
    get_ed_appdata_path,
    get_ed_journals_path,
    get_system_info,
    load_config,
    load_hud_color_matrix,
    save_config,
    update_config,
    update_event_config,
    validate_config,
    update_character,
    reset_game_events,
)
from lib.PluginManager import PluginManager
from lib.ActionManager import ActionManager


def parse_plugin_provider(provider: str) -> tuple[str, str] | None:
    """
    Parse a plugin provider string in format 'plugin:<guid>:<id>'.

    Returns:
        Tuple of (plugin_guid, provider_id) or None if not a plugin provider
    """
    if not provider.startswith("plugin:"):
        return None
    parts = provider.split(":", 2)
    if len(parts) != 3:
        return None
    return (parts[1], parts[2])


from lib.actions.Actions import register_actions
from lib.ControllerManager import ControllerManager
from lib.EDKeys import EDKeys
from lib.Event import (
    ConversationEvent,
    Event,
    ExternalEvent,
    GameEvent,
    MemoryEvent,
    QuestEvent,
    ProjectedEvent,
    StatusEvent,
    ToolEvent,
    PluginEvent,
)
from lib.Logger import show_chat_message, configure_stdio
from lib.Projections import registerProjections
from lib.PromptGenerator import PromptGenerator
from lib.STT import STT
from lib.TTS import TTS
from lib.StatusParser import StatusParser
from lib.EDJournal import *
from lib.EventManager import EventManager
from lib.UI import send_message, emit_message
from lib.QuestCatalogManager import QuestCatalogManager
from lib.SystemDatabase import SystemDatabase
from lib.Database import ModelUsageStore, QuestDatabase, VectorStore
from lib.Assistant import Assistant
from lib.NonKgbfoamJumpWarning import (
    NonKgbfoamJumpWarningController,
    configured_warning_language,
    format_star_warning,
    format_unknown_class_warning,
)
from lib.CloseStarJumpGuard import (
    CloseStarJumpGuardController,
    format_close_star_guard_warning,
    format_unsafe_plotted_route_warning,
)
from lib.RouteBypassPlanner import find_verified_safe_bypass
from lib.RouteSafety import (
    ROUTE_SAFETY_CACHE,
    RouteSafetyPolicy,
    SystemSafetyAssessment,
    assess_star_system,
    route_safety_policy_from_config,
    star_geometry_from_edsm,
    star_geometry_from_journal,
)
from lib.RouteSafetyProvider import prefetch_spansh_systems_nonblocking
from lib.RouteSafetySupervisor import RouteHop, RouteSafetySupervisor, SupervisorDecision
from lib.Screenshot import set_game_window_active


def get_model_usage_history_payload(
    model_usage_store: ModelUsageStore,
    usage_kind: str | None = None,
    from_timestamp: str | None = None,
    to_timestamp: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    try:
        normalized_limit = min(max(int(limit), 1), 1000)
        normalized_offset = max(int(offset), 0)
    except (TypeError, ValueError):
        return {"error": "Invalid limit or offset"}

    try:
        rows, total = model_usage_store.get_history(
            usage_kind=usage_kind,
            start_time=from_timestamp,
            end_time=to_timestamp,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return {
            "rows": rows,
            "total": total,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "usage_kind": usage_kind,
            "from": from_timestamp,
            "to": to_timestamp,
        }
    except Exception as e:
        log("error", f"Error fetching model usage history: {e}")
        log("error", traceback.format_exc())
        return {"error": str(e)}


@final
class Chat:
    def __init__(self, config: Config, plugin_manager: PluginManager):
        self.config = config  # todo: remove
        self.plugin_manager = plugin_manager
        if self.config["api_key"] == "":
            self.config["api_key"] = "-"
        self.character = self.config["characters"][
            self.config["active_character_index"]
        ]

        self.voice_instructions = self.character["tts_prompt"]

        self.backstory = self.character["character"].replace(
            "{commander_name}", self.config["commander_name"]
        )

        self.enabled_game_events: list[str] = []
        disabled_events: list[str] = []
        event_reactions = self.character.get("event_reactions", {})
        if self.character.get("event_reaction_enabled_var", False):
            for event, state in event_reactions.items():
                if state == "on":
                    self.enabled_game_events.append(event)
                if state == "hidden":
                    disabled_events.append(event)

        log("debug", "Initializing Controller Manager...")
        self.controller_manager = ControllerManager()

        log("debug", "Initializing Action Manager...")
        self.action_manager = ActionManager()
        # Set enabled action permissions from config. Missing keys are disabled.
        try:
            self.action_manager.set_allowed_actions(
                self.config.get("allowed_actions", {})
            )
        except Exception:
            self.action_manager.set_allowed_actions({})

        log("debug", "Initializing EDJournal...")
        self.jn = EDJournal(get_ed_journals_path(config))

        # gets API Key from config.json
        # LLM model - check for plugin provider
        llm_plugin = parse_plugin_provider(self.config["llm_provider"])
        if llm_plugin:
            model = self.plugin_manager.create_plugin_model(
                llm_plugin[0], llm_plugin[1], "llm"
            )
            if model is None:
                show_chat_message(
                    "error",
                    f"Failed to create LLM from plugin provider. Check logs for details.",
                )
                raise RuntimeError(
                    f"Failed to create LLM from plugin provider {self.config['llm_provider']}"
                )
            self.llmModel = cast(LLMModel, model)
        else:
            self.llmModel = create_llm_model(
                self.config["llm_provider"], self.config, "llm"
            )

        # Agent LLM model - check for plugin provider
        agent_llm_plugin = parse_plugin_provider(self.config["agent_llm_provider"])
        if agent_llm_plugin:
            model = self.plugin_manager.create_plugin_model(
                agent_llm_plugin[0], agent_llm_plugin[1], "llm"
            )
            if model is None:
                show_chat_message(
                    "error",
                    f"Failed to create Agent LLM from plugin provider. Check logs for details.",
                )
                raise RuntimeError(
                    f"Failed to create Agent LLM from plugin provider {self.config['agent_llm_provider']}"
                )
            self.agent_llm_model = cast(LLMModel, model)
        else:
            self.agent_llm_model = create_llm_model(
                self.config["agent_llm_provider"], self.config, "agent_llm"
            )

        # embeddings
        self.embeddingModel: EmbeddingModel | None = None
        embedding_provider = self.config.get("embedding_provider", "")
        embedding_plugin = parse_plugin_provider(embedding_provider)
        if embedding_plugin:
            model = self.plugin_manager.create_plugin_model(
                embedding_plugin[0], embedding_plugin[1], "embedding"
            )
            if model is None:
                show_chat_message(
                    "warning",
                    f"Failed to create Embedding model from plugin provider. Embeddings disabled.",
                )
            else:
                self.embeddingModel = cast(EmbeddingModel, model)
        elif embedding_provider in [
            "openai",
            "custom",
            "google-ai-studio",
            "local-ai-server",
        ]:
            self.embeddingModel = create_embedding_model(
                embedding_provider, self.config, "embedding"
            )

        # vision
        self.visionModel: LLMModel | None = None
        if self.config["vision_var"]:
            vision_provider = self.config.get("vision_provider", "openai")
            vision_plugin = parse_plugin_provider(vision_provider)
            if vision_plugin:
                model = self.plugin_manager.create_plugin_model(
                    vision_plugin[0], vision_plugin[1], "llm"
                )
                if model is None:
                    show_chat_message(
                        "warning",
                        f"Failed to create Vision model from plugin provider. Vision disabled.",
                    )
                else:
                    self.visionModel = cast(LLMModel, model)
            else:
                self.visionModel = create_llm_model(
                    vision_provider, self.config, "vision"
                )

        log("debug", "Initializing Speech processing...")
        self.sttModel: STTModel | None = None
        if self.config["stt_provider"] != "none":
            stt_plugin = parse_plugin_provider(self.config["stt_provider"])
            if stt_plugin:
                model = self.plugin_manager.create_plugin_model(
                    stt_plugin[0], stt_plugin[1], "stt"
                )
                if model is None:
                    show_chat_message(
                        "warning",
                        f"Failed to create STT model from plugin provider. STT disabled.",
                    )
                else:
                    self.sttModel = cast(STTModel, model)
            else:
                self.sttModel = create_stt_model(
                    self.config["stt_provider"], self.config, "stt"
                )

        self.ttsModel: TTSModel | None = None
        if self.config["tts_provider"] != "none":
            tts_plugin = parse_plugin_provider(self.config["tts_provider"])
            if tts_plugin:
                model = self.plugin_manager.create_plugin_model(
                    tts_plugin[0], tts_plugin[1], "tts"
                )
                if model is None:
                    show_chat_message(
                        "warning",
                        f"Failed to create TTS model from plugin provider. TTS disabled.",
                    )
                else:
                    self.ttsModel = cast(TTSModel, model)
            else:
                # Create a config copy with character specific settings
                tts_config = dict(self.config.copy())
                tts_config["tts_speed"] = float(self.character["tts_speed"])
                tts_config["tts_voice_instructions"] = self.character["tts_prompt"]
                self.ttsModel = create_tts_model(
                    self.config["tts_provider"], tts_config, "tts"
                )

                if self.ttsModel is not None and self.config.get("tts_warmup_enabled", False):
                    warmup_language = str(self.config.get("tts_language", "en")).lower()
                    warmup_text = (
                        "COVAS en ligne. Tous les systèmes sont opérationnels."
                        if warmup_language.startswith("fr")
                        else "COVAS online. All systems are operational."
                    )

                    def warm_tts_model() -> None:
                        try:
                            for _ in self.ttsModel.synthesize(
                                warmup_text,
                                self.character["tts_voice"],
                            ):
                                pass
                            log("info", "TTS warm-up completed")
                        except Exception as warmup_error:
                            log("warn", "TTS warm-up failed", warmup_error)

                    threading.Thread(target=warm_tts_model, daemon=True).start()

        self.tts = TTS(
            tts_model=self.ttsModel,
            voice=self.character["tts_voice"],
            speed=float(self.character["tts_speed"]),
            postprocessing_config=self.character.get("tts_postprocessing"),
            output_device=self.config["output_device_name"],
            output_volume_multiplier=float(
                self.config.get("output_volume_multiplier", 1.0)
            ),
            debug_capture_enabled=bool(
                self.config.get("tts_debug_capture_enabled", False)
            ),
        )
        self.stt = STT(
            stt_model=self.sttModel,
            input_device_name=self.config["input_device_name"],
            required_word=self.config["stt_required_word"],
        )

        log("debug", "Initializing SystemDatabase...")
        self.system_database = SystemDatabase()
        log("debug", "Initializing QuestDatabase...")
        self.quest_database = QuestDatabase()
        log("debug", "Initializing ModelUsageStore...")
        self.model_usage_store = ModelUsageStore()
        log("debug", "Initializing EDKeys...")
        self.ed_keys = EDKeys(
            get_ed_appdata_path(config),
            prefer_primary_bindings=self.config.get("prefer_primary_bindings", False),
        )
        log("debug", "Initializing status parser...")
        self.status_parser = StatusParser(get_ed_journals_path(config))
        log("debug", "Initializing prompt generator...")
        self.prompt_generator = PromptGenerator(
            self.config["commander_name"],
            self.character["character"],
            important_game_events=self.enabled_game_events,
            system_db=self.system_database,
            weapon_types=cast(list[dict], self.config.get("weapon_types", [])),
            disabled_game_events=disabled_events,
        )

        log("debug", "Initializing event manager...")
        self.event_manager = EventManager(
            game_events=self.enabled_game_events,
        )

        log("debug", message="Initializing assistant...")
        self.assistant = Assistant(
            config=self.config,
            enabled_game_events=self.enabled_game_events,
            event_manager=self.event_manager,
            action_manager=self.action_manager,
            llmModel=self.llmModel,
            tts=self.tts,
            prompt_generator=self.prompt_generator,
            embeddingModel=self.embeddingModel,
            disabled_game_events=disabled_events,
        )
        self.quest_catalog_manager = QuestCatalogManager(
            reload_callback=self.assistant._load_quests,
        )
        self.is_replying = False
        self.listening = False

        log("debug", "Registering side effect...")
        self.event_manager.register_sideeffect(self.on_event)
        self.event_manager.register_sideeffect(self.assistant.on_event)

        self.plugin_helper = PluginHelper(
            self.plugin_manager,
            self.prompt_generator,
            config,
            self.action_manager,
            self.event_manager,
            self.llmModel,
            self.visionModel,
            self.system_database,
            self.ed_keys,
            self.assistant,
        )
        log("debug", "Plugin helper is ready...")

        self.previous_states = {}
        self.non_kgbfoam_jump_warning = NonKgbfoamJumpWarningController()
        self.close_star_jump_guard = CloseStarJumpGuardController()
        self.route_safety_supervisor = RouteSafetySupervisor()
        self._route_safety_lock = threading.RLock()
        self._route_safety_generation = 0

    def emit_runtime_state(self):
        _, projected_states = self.event_manager.get_current_state()
        emit_message("running_config", config=self.config)
        emit_message("system", system=get_system_info())
        emit_message("states", states=projected_states)
        self.previous_states = copy.deepcopy(projected_states)

    def _handle_non_kgbfoam_jump_warning(
        self,
        event: Event,
        projected_states: dict[str, Any],
    ) -> None:
        decision = self.non_kgbfoam_jump_warning.process(
            event,
            warning_enabled=bool(
                self.config.get("qol_non_kgbfoam_jump_warning", True)
            ),
            unknown_warning_enabled=bool(
                self.config.get("qol_non_kgbfoam_unknown_warning", False)
            ),
        )
        if decision is None:
            return

        language = configured_warning_language(cast(dict[str, object], self.config))
        warning_text = (
            format_star_warning(decision.profile, language)
            if decision.profile is not None
            else format_unknown_class_warning(language)
        )

        # This uses the normal voice queue and current environmental effects,
        # but deliberately bypasses the assistant reply/LLM path.
        show_chat_message("covas", warning_text)

        def on_start() -> None:
            self.event_manager.add_assistant_speaking()

        def on_complete() -> None:
            if not self.tts.has_queued_items():
                self.event_manager.add_assistant_complete_event()

        self.tts.say(
            warning_text,
            context="navigation_warning",
            postprocessing_layers=self.assistant._get_tts_postprocessing_layers(
                cast(Any, projected_states)
            ),
            on_start=on_start,
            on_complete=on_complete,
        )

    def _route_safety_policy(self) -> RouteSafetyPolicy:
        return route_safety_policy_from_config(cast(dict[str, Any], self.config))

    @staticmethod
    def _route_hops(route: object) -> list[RouteHop]:
        if not isinstance(route, list):
            return []
        hops: list[RouteHop] = []
        for entry in route:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("StarSystem") or "").strip()
            if not name:
                continue
            address = entry.get("SystemAddress")
            if not isinstance(address, int) or isinstance(address, bool):
                address = None
            raw_position = entry.get("StarPos")
            coordinates = None
            if (
                isinstance(raw_position, list)
                and len(raw_position) >= 3
                and all(isinstance(value, (int, float)) for value in raw_position[:3])
            ):
                coordinates = tuple(float(value) for value in raw_position[:3])
            hops.append(RouteHop(name, address, coordinates))
        return hops

    def _speak_route_safety_message(
        self,
        text: str,
        projected_states: dict[str, Any],
    ) -> None:
        show_chat_message("covas", text)

        def on_start() -> None:
            self.event_manager.add_assistant_speaking()

        def on_complete() -> None:
            if not self.tts.has_queued_items():
                self.event_manager.add_assistant_complete_event()

        self.tts.say(
            text,
            context="route_safety",
            postprocessing_layers=self.assistant._get_tts_postprocessing_layers(
                cast(Any, projected_states)
            ),
            on_start=on_start,
            on_complete=on_complete,
        )

    def _lookup_route_safety_assessment(
        self,
        system_address: int,
    ) -> SystemSafetyAssessment | None:
        policy = self._route_safety_policy()
        cached = ROUTE_SAFETY_CACHE.get(system_address, policy)
        if cached is not None:
            return cached
        record = self.system_database.get_system_by_address(system_address)
        if not isinstance(record, dict):
            return None
        system_info = record.get("system_info")
        bodies = system_info.get("bodies") if isinstance(system_info, dict) else None
        if not isinstance(bodies, list) or not bodies:
            return None
        stars = []
        for body in bodies:
            if not isinstance(body, dict):
                continue
            journal_scan = body.get("journal_scan")
            star = (
                star_geometry_from_journal(journal_scan)
                if isinstance(journal_scan, dict)
                else star_geometry_from_edsm(body)
            )
            if star is not None:
                stars.append(star)
        if not stars:
            return None
        assessment = assess_star_system(
            str(record.get("name") or "Unknown system"),
            stars,
            policy,
            system_id64=system_address,
        )
        ROUTE_SAFETY_CACHE.put(assessment, policy)
        return assessment

    def _plot_supervised_system(
        self,
        target: RouteHop | None,
        projected_states: dict[str, Any],
    ) -> bool:
        if target is None:
            return False
        descriptor = self.action_manager.actions.get("plotToTarget")
        if not descriptor:
            return False
        try:
            result = str(descriptor["method"]({"system": target.name}, projected_states))
        except Exception:
            return False
        lowered = result.casefold()
        return "successfully plotted" in lowered or "already set" in lowered or "already in" in lowered

    def _manual_bypass_warning(
        self,
        reason: str,
        projected_states: dict[str, Any],
    ) -> None:
        language = configured_warning_language(cast(dict[str, object], self.config))
        text = (
            f"Contournement automatique interrompu : {reason} Trace manuellement un système KGBFOAM sûr autour du danger."
            if language == "fr"
            else f"Automatic bypass stopped: {reason} Plot a known-safe KGBFOAM system around the hazard manually."
        )
        self._speak_route_safety_message(text, projected_states)

    def _find_and_plot_bypass(self, projected_states: dict[str, Any]) -> None:
        with self._route_safety_lock:
            boundary = self.route_safety_supervisor.boundary
            dangerous = self.route_safety_supervisor.dangerous
            destination = self.route_safety_supervisor.original_destination
            forbidden = set(self.route_safety_supervisor.forbidden_system_ids)
        if boundary is None or dangerous is None or destination is None:
            self._manual_bypass_warning("route state is incomplete.", projected_states)
            return
        ship = projected_states.get("ShipInfo")
        ship_dict = ship.model_dump() if hasattr(ship, "model_dump") else ship
        jump_range = 0.0
        if isinstance(ship_dict, dict):
            for field in ("CurrentJumpRange", "MaximumJumpRange", "ReportedMaximumJumpRange"):
                value = ship_dict.get(field)
                if isinstance(value, (int, float)) and value > 0:
                    jump_range = float(value)
                    break
        candidate, error = find_verified_safe_bypass(
            boundary,
            dangerous,
            destination,
            jump_range,
            forbidden,
            self._route_safety_policy(),
        )
        if candidate is None:
            with self._route_safety_lock:
                self.route_safety_supervisor.require_manual_bypass()
            self._manual_bypass_warning(error or "no verified-safe waypoint was found.", projected_states)
            return
        with self._route_safety_lock:
            self.route_safety_supervisor.set_bypass(candidate.hop)
        language = configured_warning_language(cast(dict[str, object], self.config))
        if candidate.safety_status == "safe":
            text = (
                f"Replanification vers l'intermédiaire KGBFOAM vérifié {candidate.hop.name}, à {candidate.jump_distance_ly:.2f} années-lumière."
                if language == "fr"
                else f"Replotting to verified-safe KGBFOAM intermediate {candidate.hop.name}, {candidate.jump_distance_ly:.2f} light-years away."
            )
        else:
            text = (
                f"Aucun intermédiaire prouvé sûr. Je tente {candidate.hop.name}, une étoile KGBFOAM à {candidate.jump_distance_ly:.2f} années-lumière, mais sa géométrie stellaire est inconnue. Prudence."
                if language == "fr"
                else f"No positively safe intermediate was found. I am trying {candidate.hop.name}, a KGBFOAM star {candidate.jump_distance_ly:.2f} light-years away, but its companion geometry is unknown. Use caution."
            )
        self._speak_route_safety_message(text, projected_states)
        if not self._plot_supervised_system(candidate.hop, projected_states):
            with self._route_safety_lock:
                self.route_safety_supervisor.require_manual_bypass()
            self._manual_bypass_warning("the intermediate route could not be plotted.", projected_states)

    def _execute_supervisor_decision(
        self,
        decision: SupervisorDecision,
        projected_states: dict[str, Any],
    ) -> None:
        language = configured_warning_language(cast(dict[str, object], self.config))
        if decision.action == "route_safe":
            text = "Route vérifiée sûre." if language == "fr" else "Route verified safe."
            self._speak_route_safety_message(text, projected_states)
            return
        if decision.action == "route_accepted_unknown":
            text = (
                f"Route acceptée avec {decision.unknown_hops} système{'s' if decision.unknown_hops != 1 else ''} dont la géométrie stellaire est inconnue."
                if language == "fr"
                else f"Route accepted with {decision.unknown_hops} system{'s' if decision.unknown_hops != 1 else ''} whose close-star geometry is unknown."
            )
            self._speak_route_safety_message(text, projected_states)
            return
        if decision.action == "plot_boundary":
            text = format_unsafe_plotted_route_warning(
                decision.dangerous.name if decision.dangerous else "Unknown",
                decision.target.name if decision.target else "Unknown",
                decision.hop_number or 1,
                language,
            )
            self._speak_route_safety_message(text, projected_states)
            if not self._plot_supervised_system(decision.target, projected_states):
                with self._route_safety_lock:
                    self.route_safety_supervisor.require_manual_bypass()
                self._manual_bypass_warning("the safe-prefix route could not be plotted.", projected_states)
            return
        if decision.action == "find_bypass":
            if decision.dangerous is not None:
                self._speak_route_safety_message(
                    format_unsafe_plotted_route_warning(
                        decision.dangerous.name,
                        decision.target.name if decision.target else "current system",
                        decision.hop_number or 1,
                        language,
                    ),
                    projected_states,
                )
            self._find_and_plot_bypass(projected_states)
            return
        if decision.action == "plot_original":
            text = (
                "Intermédiaire atteint. Replanification vers la destination d'origine et nouvelle vérification."
                if language == "fr"
                else "Intermediate reached. Replotting the original destination and checking the route again."
            )
            self._speak_route_safety_message(text, projected_states)
            if not self._plot_supervised_system(decision.target, projected_states):
                with self._route_safety_lock:
                    self.route_safety_supervisor.require_manual_bypass()
                self._manual_bypass_warning("the original destination could not be replotted.", projected_states)
            return
        if decision.action == "manual_bypass_required":
            self._manual_bypass_warning(decision.message, projected_states)

    def _handle_route_safety_prefetch(
        self,
        event: Event,
        projected_states: dict[str, Any],
    ) -> None:
        if not isinstance(event, GameEvent):
            return
        policy = self._route_safety_policy()
        if not policy.enabled:
            return
        event_name = event.content.get("event")
        if event_name == "NavRoute":
            route = self._route_hops(event.content.get("Route"))
            if len(route) < 2:
                return
            systems = {
                hop.system_address: hop.name
                for hop in route[1:]
                if hop.system_address is not None
            }
            with self._route_safety_lock:
                self._route_safety_generation += 1
                generation = self._route_safety_generation

            def on_complete(_assessments, _error) -> None:
                with self._route_safety_lock:
                    if generation != self._route_safety_generation:
                        return
                    decision = self.route_safety_supervisor.inspect_route(
                        route,
                        self._lookup_route_safety_assessment,
                    )
                self._execute_supervisor_decision(decision, projected_states)

            prefetch_spansh_systems_nonblocking(
                systems,
                policy,
                on_complete=on_complete,
            )
        elif event_name == "FSDTarget":
            address = event.content.get("SystemAddress")
            name = str(event.content.get("Name") or "").strip()
            if isinstance(address, int) and name:
                prefetch_spansh_systems_nonblocking({address: name}, policy)

    def _handle_close_star_jump_guard(
        self,
        event: Event,
        projected_states: dict[str, Any],
    ) -> None:
        enabled = bool(self.config.get("route_safety_close_star_enabled", True)) and bool(
            self.config.get("route_safety_cancel_dangerous_charge", True)
        )
        decision = self.close_star_jump_guard.process(
            event,
            enabled=enabled,
            lookup=self._lookup_route_safety_assessment,
        )
        if decision is None:
            return
        cancelled = False
        try:
            set_game_window_active()
            self.ed_keys.send("Hyperspace")
            cancelled = True
        except Exception:
            cancelled = False
        language = configured_warning_language(cast(dict[str, object], self.config))
        self._speak_route_safety_message(
            format_close_star_guard_warning(
                decision,
                language,
                cancelled=cancelled,
            ),
            projected_states,
        )

    def _warn_if_next_route_hop_is_unmapped(
        self,
        projected_states: dict[str, Any],
    ) -> None:
        if not self._route_safety_policy().enabled:
            return
        nav_info = projected_states.get("NavInfo")
        nav_dict = nav_info.model_dump() if hasattr(nav_info, "model_dump") else nav_info
        route = self._route_hops(nav_dict.get("NavRoute") if isinstance(nav_dict, dict) else None)
        if not route:
            return
        next_hop = route[0]
        assessment = (
            self._lookup_route_safety_assessment(next_hop.system_address)
            if next_hop.system_address is not None else None
        )
        if assessment is not None and assessment.status != "unknown":
            return
        language = configured_warning_language(cast(dict[str, object], self.config))
        text = (
            f"Prochain système : {next_hop.name}. Sa géométrie stellaire n'est pas cartographiée ; le risque d'étoiles proches ne peut pas être évalué."
            if language == "fr"
            else f"Next system: {next_hop.name}. Its star geometry is unmapped, so close-star arrival risk cannot be evaluated."
        )
        self._speak_route_safety_message(text, projected_states)

    def on_event(self, event: Event, projected_states: dict[str, Any]):
        self._handle_route_safety_prefetch(event, projected_states)
        self._handle_close_star_jump_guard(event, projected_states)
        self._handle_non_kgbfoam_jump_warning(event, projected_states)
        if isinstance(event, GameEvent) and event.content.get("event") == "FSDJump":
            self._warn_if_next_route_hop_is_unmapped(projected_states)
            arrived = self._route_hops([{
                "StarSystem": event.content.get("StarSystem"),
                "SystemAddress": event.content.get("SystemAddress"),
                "StarPos": event.content.get("StarPos"),
            }])
            if arrived:
                with self._route_safety_lock:
                    supervisor_decision = self.route_safety_supervisor.on_jump(arrived[0])
                if supervisor_decision.action != "none":
                    threading.Thread(
                        target=self._execute_supervisor_decision,
                        args=(supervisor_decision, projected_states),
                        name="route-safety-supervisor",
                        daemon=True,
                    ).start()
        for key, value in projected_states.items():
            if self.previous_states.get(key, None) != value:
                send_message(
                    {
                        "type": "states",
                        "states": {key: value},
                    }
                )
        self.previous_states = copy.deepcopy(projected_states)
        send_message(
            {
                "type": "event",
                "event": event,
            }
        )
        if event.kind == "assistant":
            event = cast(ConversationEvent, event)
            show_chat_message("covas", event.content)
        if event.kind == "user":
            event = cast(ConversationEvent, event)
            show_chat_message("cmdr", event.content)
        if event.kind == "tool":
            event = cast(ToolEvent, event)
            show_chat_message(
                "action",
                "\n".join(
                    event.text
                    if event.text
                    else [
                        r.get("function", {}).get("name", "Unknown")
                        for r in event.request
                    ]
                ),
            )
        if event.kind == "game":
            event = cast(GameEvent, event)
            show_chat_message("event", event.content.get("event", "Unknown"))
        if event.kind == "status":
            event = cast(StatusEvent, event)
            if event.status.get("event", "Unknown") != "Status":
                show_chat_message("event", event.status.get("event", "Unknown"))
        if event.kind == "external":
            event = cast(ExternalEvent, event)
            show_chat_message("event", event.content.get("event", "Unknown"))
        if event.kind == "projected":
            event = cast(ProjectedEvent, event)
            show_chat_message("event", event.content.get("event", "Unknown"))
        if event.kind == "memory":
            event = cast(MemoryEvent, event)
            show_chat_message("memory", event.content)
        if event.kind == "plugin":
            event = cast(PluginEvent, event)
            plugin_content = event.plugin_event_content if isinstance(event.plugin_event_content, dict) else {}
            plugin_message = plugin_content.get("text")
            avatar_url = plugin_content.get("avatar_url")
            show_chat_message(
                "plugin",
                plugin_message if isinstance(plugin_message, str) and plugin_message.strip() else event.plugin_event_name,
                plugin_event_name=event.plugin_event_name,
                avatar_url=avatar_url if isinstance(avatar_url, str) and avatar_url else None,
            )
        if event.kind == "quest":
            event = cast(QuestEvent, event)
            action_value = event.content.get("action") if isinstance(event.content, dict) else None
            action_name = (
                action_value
                if isinstance(action_value, str) and action_value in ["play_sound", "npc_message"]
                else None
            )
            is_audio_quest_action = action_name is not None
            if not is_audio_quest_action:
                show_chat_message("quest", event.content)
            if is_audio_quest_action:
                self._schedule_quest_audio_event(action_name, cast(dict[str, Any], event.content))

        if isinstance(event, GameEvent) and event.content.get("event") == "FSDTarget":
            if "Name" in event.content:
                system_name = event.content.get("Name", "Unknown")
                cached_info = (
                    self.system_database.get_cached_system_info(system_name)
                    if system_name != "Unknown" else {}
                )
                self.system_database.record_fsd_target(cast(dict[str, Any], event.content))
                if system_name != "Unknown" and not cached_info.get("bodies"):
                    self.system_database.fetch_system_data_nonblocking(system_name)

        if isinstance(event, GameEvent) and event.content.get("event") in [
            "Location",
            "CarrierLocation",
        ]:
            system_name = event.content.get("StarSystem", "Unknown")
            if system_name != "Unknown" and not self.system_database.has_system(
                system_name
            ):
                self.system_database.fetch_system_data_nonblocking(system_name)

        if (
            isinstance(event, GameEvent)
            and event.content.get("event") == "FSSDiscoveryScan"
        ):
            self.system_database.record_discovery_scan(
                cast(dict[str, Any], event.content)
            )
        if (
            isinstance(event, GameEvent)
            and event.content.get("event") == "FSSSignalDiscovered"
        ):
            self.system_database.record_signal(cast(dict[str, Any], event.content))
        if isinstance(event, GameEvent) and event.content.get("event") == "Scan":
            self.system_database.record_scan(cast(dict[str, Any], event.content))
        if (
            isinstance(event, GameEvent)
            and event.content.get("event") == "ScanBaryCentre"
        ):
            bary_event = dict(event.content)
            body_id = bary_event.get("BodyID")
            if body_id is not None:
                bary_event.setdefault("BodyName", f"Barycentre {body_id}")
            bary_event.setdefault("BodyType", "Barycentre")
            self.system_database.record_scan(cast(dict[str, Any], bary_event))
        if (
            isinstance(event, GameEvent)
            and event.content.get("event") == "SAASignalsFound"
        ):
            self.system_database.record_saa_signals_found(
                cast(dict[str, Any], event.content)
            )
        if (
            isinstance(event, GameEvent)
            and event.content.get("event") == "FSSBodySignals"
        ):
            self.system_database.record_fss_body_signals(
                cast(dict[str, Any], event.content)
            )
        if isinstance(event, GameEvent) and event.content.get("event") == "ScanOrganic":
            self.system_database.record_scan_organic(
                cast(dict[str, Any], event.content)
            )

    def submit_input(self, input: str):
        self.event_manager.add_conversation_event("user", input)

    def query_memories(self, query: str, top_k: int = 5):
        """Query long-term memories without triggering LLM interaction"""
        if not self.embeddingModel:
            return {"error": "Embeddings model not configured"}

        try:
            # Create embedding for the query
            (model_name, embedding) = self.embeddingModel.create_embedding(query)

            # Search the vector store
            results = self.event_manager.long_term_memory.search(
                query, model_name, embedding, n=min(max(1, top_k), 20)
            )

            if not results:
                return {"results": []}

            formatted = []
            for result in results:
                # Fetch inserted_at timestamp for this entry
                time_until: float = result["metadata"].get(
                    "time_until", result["inserted_at"]
                )
                time_since: float = result["metadata"].get(
                    "time_since", result["inserted_at"]
                )
                item = {
                    "score": round(result["score"], 3),
                    "summary": result["content"],
                    "inserted_at": result["inserted_at"],
                    "time_until": time_until,
                    "time_since": time_since,
                }

                formatted.append(item)

            return {"results": formatted}

        except Exception as e:
            log("error", f"Error querying memories: {e}")
            import traceback

            log("error", traceback.format_exc())
            return {"error": str(e)}

    def get_memories_by_date(self, date_str: str):
        """Fetch all memory entries for a specific date"""
        try:
            # Parse the date string (format: YYYY-MM-DD)
            target_date = datetime.fromisoformat(date_str).date()
            entries = self.event_manager.long_term_memory.get_entries_by_date(
                target_date
            )
            return {
                "entries": [
                    {
                        "id": e["id"],
                        "content": e["content"],
                        "inserted_at": e["inserted_at"],
                        "time_since": e["metadata"].get("time_since", e["inserted_at"]),
                        "time_until": e["metadata"].get("time_until", e["inserted_at"]),
                    }
                    for e in entries
                ],
                "date": date_str,
            }
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}
        except Exception as e:
            log("error", f"Error fetching memories by date: {e}")
            import traceback

            log("error", traceback.format_exc())
            return {"error": str(e)}

    def get_available_dates(self):
        """Fetch all dates that have memory entries"""
        try:
            dates = self.event_manager.long_term_memory.get_available_dates()
            return {"dates": dates}
        except Exception as e:
            log("error", f"Error fetching available dates: {e}")
            import traceback

            log("error", traceback.format_exc())
            return {"error": str(e)}

    def get_model_usage_history(
        self,
        usage_kind: str | None = None,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        return get_model_usage_history_payload(
            model_usage_store=self.model_usage_store,
            usage_kind=usage_kind,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            limit=limit,
            offset=offset,
        )

    def get_system_event_data(self, system_address: int | str | None):
        """Fetch cached system event data for a given system address."""
        if system_address is None:
            return {"error": "system_address is required"}
        try:
            address_int = int(system_address)
        except (TypeError, ValueError):
            return {"error": "Invalid system_address"}

        try:
            record = self.system_database.get_system_by_address(address_int)
            if record is None:
                return {"data": None}
            return {"data": record}
        except Exception as e:
            log("error", f"Error fetching system event data: {e}")
            import traceback

            log("error", traceback.format_exc())
            return {"error": str(e)}

    def _load_quest_catalog(self) -> dict[str, dict[str, Any]]:
        quests_path = Path(__file__).resolve().parent / "data" / "quests.yaml"
        try:
            with quests_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except Exception:
            return {}
        raw_quests = data.get("quests", [])
        if not isinstance(raw_quests, list):
            return {}
        quests: dict[str, dict[str, Any]] = {}
        for quest in raw_quests:
            if not isinstance(quest, dict):
                continue
            quest_id = quest.get("id")
            if isinstance(quest_id, str):
                quests[quest_id] = quest
        return quests

    def _find_stage_def(
        self, quest_def: dict[str, Any], stage_id: str
    ) -> dict[str, Any] | None:
        for stage in quest_def.get("stages", []):
            if isinstance(stage, dict) and stage.get("id") == stage_id:
                return stage
        return None


    def get_quest_overview(self) -> dict[str, Any]:
        try:
            quest_states = [
                state for state in self.quest_database.get_all() if state["active"]
            ]
            if not quest_states:
                return {"quests": []}
            catalog = self._load_quest_catalog()
            quests: list[dict[str, Any]] = []
            for state in quest_states:
                quest_def = catalog.get(state["quest_id"], {})
                stage_def = (
                    self._find_stage_def(quest_def, state["stage_id"])
                    if quest_def
                    else None
                )
                quests.append(
                    {
                        "id": state["quest_id"],
                        "title": quest_def.get("title", state["quest_id"])
                        if quest_def
                        else state["quest_id"],
                        "description": quest_def.get("description")
                        if quest_def
                        else None,
                        "stage_id": state["stage_id"],
                        "stage_title": stage_def.get("description")
                        if stage_def
                        else state["stage_id"],
                        "instructions": stage_def.get("instructions")
                        if stage_def
                        else None,
                    }
                )
            return {"quests": quests}
        except Exception as e:
            log("error", f"Error fetching quest overview: {e}")
            log("error", traceback.format_exc())
            return {"error": str(e)}

    def run(self):
        show_chat_message(
            "info",
            f"Initializing CMDR {self.config['commander_name']}'s personal AI...\n",
        )
        show_chat_message("info", "API Key: Loaded")
        show_chat_message("info", f"Mic Mode: {self.config['ptt_var']}")
        show_chat_message("info", f"Using Function Calling: {self.config['tools_var']}")
        show_chat_message("info", f"Current model: {self.config['llm_model_name']}")
        show_chat_message("info", f"Current TTS voice: {self.character['tts_voice']}")
        show_chat_message("info", f"Current TTS Speed: {self.character['tts_speed']}")
        show_chat_message("info", "Current backstory: " + self.backstory)

        # TTS Setup
        show_chat_message("info", "Basic configuration complete.")
        show_chat_message("info", "Loading voice output...")

        # Microphone/Listening setup based on mode
        mode = self.config.get("ptt_var", "voice_activation")
        ptt_keys = [
            key
            for key in [
                self.config.get("ptt_key", ""),
                self.config.get("ptt_key_secondary", ""),
            ]
            if key
        ]
        if mode == "push_to_talk" and ptt_keys:
            log("info", f"Setting push-to-talk hotkeys {ptt_keys}.")
            self.controller_manager.register_hotkey(
                ptt_keys,
                lambda _: self.stt.listen_once_start(),
                lambda _: self.stt.listen_once_end(),
            )
        elif mode == "push_to_mute" and ptt_keys:
            log("info", f"Setting push-to-mute hotkeys {ptt_keys}.")
            self.stt.listen_continuous()
            self.controller_manager.register_hotkey(
                ptt_keys,
                lambda _: self.stt.pause_continuous_listening(True),
                lambda _: self.stt.pause_continuous_listening(False),
            )
        elif mode == "toggle" and ptt_keys:
            log("info", f"Setting hotkeys {ptt_keys} to toggle voice activation.")
            self.stt.listen_continuous()
            self.stt.pause_continuous_listening(
                self.config.get("ptt_inverted_var", False)
            )
            self.controller_manager.register_hotkey(
                ptt_keys,
                lambda _: _,
                lambda _: self.stt.pause_continuous_listening(
                    not self.stt.continuous_listening_paused
                ),
            )
        else:
            log("info", f"Setting automatic voice activation.")
            self.stt.listen_continuous()
        show_chat_message("info", "Voice interface ready.")

        show_chat_message("info", "Initializing states...")
        self.event_manager.add_historic_game_events(self.jn.historic_events)

        self.event_manager.add_status_event(self.status_parser.current_status)

        show_chat_message("info", "Register projections...")
        registerProjections(
            self.event_manager,
            self.system_database,
            self.character.get("idle_timeout_var", 300),
            self.character.get("bounty_scanned_min_bounty_var", 1),
        )

        self.event_manager.process()

        if self.config["tools_var"]:
            log("info", "Register actions...")
            hud_color_matrix = load_hud_color_matrix(self.config)

            register_actions(
                actionManager=self.action_manager,
                eventManager=self.event_manager,
                promptGenerator=self.prompt_generator,
                llmModel=self.llmModel,
                visionModel=self.visionModel,
                visionModelName=self.config["vision_model_name"],
                embeddingModel=self.embeddingModel,
                edKeys=self.ed_keys,
                discovery_primary_var_flag=self.config.get(
                    "discovery_primary_var", True
                ),
                discovery_firegroup_var_flag=self.config.get(
                    "discovery_firegroup_var", 1
                ),
                chat_local_tabbed_flag=self.config.get("chat_local_tabbed_var", False),
                chat_wing_tabbed_flag=self.config.get("chat_wing_tabbed_var", False),
                chat_system_tabbed_flag=self.config.get("chat_system_tabbed_var", True),
                chat_squadron_tabbed_flag=self.config.get(
                    "chat_squadron_tabbed_var", False
                ),
                chat_direct_tabbed_flag=self.config.get(
                    "chat_direct_tabbed_var", False
                ),
                overlay_show_hud=self.config.get("overlay_show_hud", False),
                weapon_types_list=self.config.get("weapon_types", []),
                agent_llm_model=self.agent_llm_model,
                agent_llm_max_tries=self.config.get("agent_llm_max_tries", 7),
                hud_color_matrix=hud_color_matrix,
                in_system_navigation_flag=self.config.get(
                    "in_system_navigation", False
                ),
            )

            log("info", "Actions ready.")
            show_chat_message("info", "Actions ready.")

        # Execute plugin helper ready hooks
        self.plugin_manager.on_chat_start(self.plugin_helper)
        show_chat_message("info", "Plugins ready.")

        # Cue the user that we're ready to go.
        show_chat_message("info", "System Ready.")

        while True:
            try:
                status = None
                # check status file for updates
                while not self.status_parser.status_queue.empty():
                    status = self.status_parser.status_queue.get()
                    self.event_manager.add_status_event(status)

                # mute continuous listening during response
                if self.config.get("mute_during_response_var"):
                    if self.tts.get_is_playing():
                        self.stt.pause_continuous_listening(True)
                    else:
                        self.stt.pause_continuous_listening(False)

                # check STT recording
                if self.stt.recording:
                    if not self.listening:
                        self.listening = True
                        self.event_manager.add_user_speaking()
                    if self.tts.get_is_playing():
                        log("debug", "interrupting TTS")
                        self.tts.abort()
                else:
                    self.listening = False

                # check STT result queue
                if not self.stt.resultQueue.empty():
                    text = self.stt.resultQueue.get().text
                    self.tts.abort()
                    self.event_manager.add_conversation_event("user", text)

                # check EDJournal files for updates
                while not self.jn.events.empty():
                    event = self.jn.events.get()
                    self.event_manager.add_game_event(event)

                self.event_manager.process()

                if (
                    self.assistant.reply_pending
                    and not self.assistant.is_replying
                    and not self.stt.recording
                    and not self.tts.get_is_playing()
                ):
                    _events, projected_states = self.event_manager.get_current_state()
                    self.assistant.reply(projected_states)

                # Infinite loops are bad for processors, must sleep.
                sleep(0.1)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log("error", e, traceback.format_exc())
                break

        # Teardown TTS
        self.tts.quit()

        # Execute plugin chat stop hooks
        self.plugin_manager.on_chat_stop(self.plugin_helper)

    def web_search(self, query: str):
        """Perform a web search using the assistant's action manager"""
        _, projected_states = self.event_manager.get_current_state()
        self.assistant.web_search(query, projected_states)

    def _resolve_quest_audio_file_path(self, file_name: str) -> Path | None:
        normalized_name = file_name.replace("\\", "/")
        if "/" in normalized_name:
            return None
        if not normalized_name.lower().endswith((".mp3", ".wav")):
            return None
        return Path(__file__).resolve().parent / "data" / "audio" / normalized_name

    def _schedule_quest_audio_event(self, action: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            log("warn", f"Invalid quest payload for action {action}: not an object")
            return
        transcription = payload.get("transcription")
        if not isinstance(transcription, str) or not transcription:
            log("warn", f"Invalid quest payload for action {action}: missing transcription")
            return
        voice = payload.get("voice")
        if not isinstance(voice, str) or not voice:
            voice = None
        actor_id = payload.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            actor_id = None
        actor_name = payload.get("actor_name")
        if not isinstance(actor_name, str) or not actor_name:
            actor_name = None
        actor_name_color = payload.get("actor_name_color")
        if not isinstance(actor_name_color, str) or not actor_name_color:
            actor_name_color = None
        avatar_url = payload.get("avatar_url")
        if not isinstance(avatar_url, str) or not avatar_url:
            avatar_url = None

        audio_file_path: Path | None = None
        if action == "play_sound":
            file_name = payload.get("file_name")
            if not isinstance(file_name, str) or not file_name:
                log("warn", "Invalid quest payload for action play_sound: missing file_name")
                return
            audio_file_path = self._resolve_quest_audio_file_path(file_name)
            if audio_file_path is None:
                log("warn", f"Invalid quest payload for action play_sound: unsafe file_name '{file_name}'")
                return
            if not audio_file_path.exists():
                log("warn", f"Quest audio file does not exist: {audio_file_path}")
                return

        def on_start() -> None:
            if action in ("npc_message", "play_sound"):
                show_chat_message(
                    "npc_message",
                    transcription,
                    actor_id=actor_id if isinstance(actor_id, str) else None,
                    actor_name=actor_name if isinstance(actor_name, str) else None,
                    display_color=actor_name_color if isinstance(actor_name_color, str) else None,
                    avatar_url=avatar_url if isinstance(avatar_url, str) else None,
                    display_name=actor_name if isinstance(actor_name, str) and actor_name else "NPC",
                )
            self.event_manager.add_assistant_speaking()

        def on_complete() -> None:
            # Avoid clearing avatar/state between back-to-back queued lines.
            # Only emit completion when this was the last queued utterance.
            if not self.tts.has_queued_items():
                self.event_manager.add_assistant_complete_event()

        if action == "play_sound" and audio_file_path is not None:
            self.tts.play_audio_file(
                str(audio_file_path),
                on_start=on_start,
                on_complete=on_complete,
                drop_if=lambda: self.stt.recording,
            )
        else:
            self.tts.say(
                transcription,
                voice=voice if isinstance(voice, str) and voice else None,
                on_start=on_start,
                on_complete=on_complete,
                drop_if=lambda: self.stt.recording,
            )


def read_stdin(chat: Chat):
    log("debug", "Reading stdin...")
    emit_message("running_config", config=config)
    while True:
        line = sys.stdin.readline().strip()
        if line:
            data = json.loads(line)
            if data.get("type") == "change_config":
                partial = data.get("config")
                if isinstance(partial, dict):
                    chat.config = update_config(chat.config, partial)
                    chat.plugin_manager.on_settings_changed(chat.config)
                    if "output_volume_multiplier" in partial:
                        chat.tts.set_output_volume_multiplier(
                            float(chat.config.get("output_volume_multiplier", 1.0))
                        )
            if data.get("type") == "submit_input":
                chat.submit_input(data["input"])
            if data.get("type") == "plugin_settings_button":
                plugin_guid = data.get("plugin_guid")
                key = data.get("key")
                if isinstance(plugin_guid, str) and isinstance(key, str):
                    chat.plugin_manager.on_settings_button(plugin_guid, key)
            if data.get("type") == "query_memories":
                query = data.get("query", "")
                top_k = data.get("top_k", 5)
                if query:
                    results = chat.query_memories(query, top_k)
                    emit_message("memory_results", results=results)
            if data.get("type") == "get_memories_by_date":
                date_str = data.get("date", "")
                if date_str:
                    results = chat.get_memories_by_date(date_str)
                    emit_message("memories_by_date", data=results)
            if data.get("type") == "get_available_dates":
                results = chat.get_available_dates()
                emit_message("available_dates", data=results)
            if data.get("type") == "get_model_usage_history":
                results = chat.get_model_usage_history(
                    usage_kind=data.get("usage_kind"),
                    from_timestamp=data.get("from"),
                    to_timestamp=data.get("to"),
                    limit=data.get("limit", 100),
                    offset=data.get("offset", 0),
                )
                emit_message("model_usage_history", data=results)
            if data.get("type") == "get_system_events":
                system_address = data.get("system_address")
                results = chat.get_system_event_data(system_address)
                emit_message(
                    "system_events",
                    system_address=system_address,
                    data=results,
                )
            if data.get("type") == "clear_history":
                chat.event_manager.clear_conversation_history()
                chat.assistant.clear_conversation_state()
                emit_message("history_cleared", scope="conversation")
            if data.get("type") == "reset_state_machine":
                chat.event_manager.reset_state_machine()
                chat.assistant.reset_runtime_state()
                chat.previous_states = {}
                emit_message("history_cleared", scope="state_machine")
            if data.get("type") == "delete_current_logbook":
                try:
                    chat.event_manager.long_term_memory.delete_all()
                    emit_message("logbook_deleted", success=True)
                except Exception as e:
                    log("error", f"Failed to delete current logbook: {e}")
                    emit_message("logbook_deleted", success=False, message=str(e))
            if data.get("type") == "get_quests":
                results = chat.get_quest_overview()
                emit_message(
                    "quests",
                    data=results,
                )
            if data.get("type") == "refresh_system_info":
                emit_message("system", system=get_system_info())
            if data.get("type") == "get_quest_catalog":
                results = chat.quest_catalog_manager.get_catalog()
                emit_message(
                    "quest_catalog",
                    data=results.get("catalog"),
                    raw=results.get("raw", ""),
                    error=results.get("error"),
                    path=results.get("path"),
                )
            if data.get("type") == "save_quest_catalog":
                save_result = chat.quest_catalog_manager.save_catalog(data.get("data"))
                emit_message(
                    "quest_catalog_saved",
                    success=save_result.get("success", False),
                    message=save_result.get("message"),
                    data=save_result.get("catalog"),
                    raw=save_result.get("raw", ""),
                )
            if data.get("type") == "reset_quest_progress":
                try:
                    chat.quest_database.delete_all()
                    emit_message("quest_progress_reset", success=True)
                except Exception as e:
                    log("error", f"Failed to reset quest progress: {e}")
                    emit_message("quest_progress_reset", success=False, message=str(e))
            if data.get("type") == "init_overlay":
                chat.emit_runtime_state()
            if data.get("type") == "web_search":
                query = data.get("query", "")
                if query:
                    chat.web_search(query)


def check_zombie_status():
    """Checks if the current process is a zombie and exits if it is."""
    log("debug", "Starting zombie process checker thread...")
    while True:
        if os.getppid() == 1:
            log("info", "Parent process exited. Exiting.")
            sleep(1)  # Give some time for the parent to exit
            os._exit(0)  # Use os._exit to avoid cleanup issues in threads
        sleep(5)  # Check every 5 seconds


if __name__ == "__main__":
    startup_phase = "bootstrap"
    try:
        configure_stdio()
        sys.stdin = io.TextIOWrapper(
            sys.stdin.buffer, encoding="utf-8", write_through=True
        )
        emit_message("ready")
        # Wait for start signal on stdin
        startup_phase = "config_load"
        config = load_config()
        load_hud_color_matrix(config)
        emit_message("config", config=config)
        system = get_system_info()
        emit_message("system", system=system)

        startup_phase = "plugin_load"
        ed_keys = EDKeys(
            get_ed_appdata_path(config),
            prefer_primary_bindings=config.get("prefer_primary_bindings", False),
        )
        # Load plugins.
        log("debug", "Loading plugins...")
        plugin_manager = PluginManager(config=config)
        plugin_manager.load_plugins()
        log("debug", "Registering plugin settings for the UI...")
        plugin_manager.register_settings()
        quest_catalog_manager = QuestCatalogManager()
        model_usage_store = ModelUsageStore()
        startup_phase = "waiting_for_start_signal"
        while True:
            # print(f"Waiting for command...")
            line = sys.stdin.readline().strip()
            # print(f"Received command: {line}")
            if not line:
                continue

            try:
                data = json.loads(line)
                if data.get("type") == "start":
                    if data.get("oldUi"):
                        config = load_config()
                        break
                    else:
                        new_config = validate_config(config)
                        if new_config:
                            config = new_config
                            break
                if data.get("type") == "assign_ptt":
                    index = data.get("index", 0)
                    config = assign_ptt(
                        config,
                        ControllerManager(),
                        index if isinstance(index, int) else 0,
                    )
                if data.get("type") == "change_config":
                    config = update_config(config, data["config"])
                    plugin_manager.on_settings_changed(config)
                if data.get("type") == "change_event_config":
                    config = update_event_config(
                        config, data["section"], data["event"], data["value"]
                    )
                if data.get("type") == "change_character":
                    config = update_character(config, data)
                if data.get("type") == "reset_game_events":
                    config = reset_game_events(config, data["character_index"])
                if data.get("type") == "clear_history":
                    EventManager.clear_history()
                    # ActionManager.clear_action_cache()
                if data.get("type") == "reset_state_machine":
                    EventManager.reset_state_machine_store()
                if data.get("type") == "delete_current_logbook":
                    try:
                        VectorStore("memory").delete_all()
                        emit_message("logbook_deleted", success=True)
                    except Exception as e:
                        log("error", f"Failed to delete current logbook: {e}")
                        emit_message("logbook_deleted", success=False, message=str(e))
                if data.get("type") == "refresh_system_info":
                    emit_message("system", system=get_system_info())
                if data.get("type") == "init_overlay":
                    update_config(config, {}) # Ensure that the overlay gets a new config on start
                if data.get("type") == "get_quest_catalog":
                    results = quest_catalog_manager.get_catalog()
                    emit_message(
                        "quest_catalog",
                        data=results.get("catalog"),
                        raw=results.get("raw", ""),
                        error=results.get("error"),
                        path=results.get("path"),
                    )
                if data.get("type") == "save_quest_catalog":
                    save_result = quest_catalog_manager.save_catalog(data.get("data"))
                    emit_message(
                        "quest_catalog_saved",
                        success=save_result.get("success", False),
                        message=save_result.get("message"),
                        data=save_result.get("catalog"),
                        raw=save_result.get("raw", ""),
                    )
                if data.get("type") == "get_model_usage_history":
                    results = get_model_usage_history_payload(
                        model_usage_store=model_usage_store,
                        usage_kind=data.get("usage_kind"),
                        from_timestamp=data.get("from"),
                        to_timestamp=data.get("to"),
                        limit=data.get("limit", 100),
                        offset=data.get("offset", 0),
                    )
                    emit_message("model_usage_history", data=results)
                if data.get("type") == "reset_quest_progress":
                    try:
                        QuestDatabase().delete_all()
                        emit_message("quest_progress_reset", success=True)
                    except Exception as e:
                        log("error", f"Failed to reset quest progress: {e}")
                        emit_message("quest_progress_reset", success=False, message=str(e))
                if data.get("type") == "plugin_settings_button":
                    plugin_guid = data.get("plugin_guid")
                    key = data.get("key")
                    if isinstance(plugin_guid, str) and isinstance(key, str):
                        plugin_manager.on_settings_button(plugin_guid, key)        
                if data.get("type") == "enable_remote_tracing":
                    from lib.Logger import enable_remote_tracing

                    enable_remote_tracing(
                        config["commander_name"], data.get("resourceAttributes", {})
                    )

            except json.JSONDecodeError:
                continue

        # Once start signal received, initialize and run chat
        save_config(config)
        plugin_manager.on_settings_changed(config)
        emit_message("start")

        startup_phase = "assistant_initialization"
        chat = Chat(config, plugin_manager)
        # run chat in a thread
        stdin_thread = threading.Thread(target=read_stdin, args=(chat,), daemon=True)
        stdin_thread.start()

        if sys.platform.startswith(("linux", "darwin")):
            zombie_check_thread = threading.Thread(
                target=check_zombie_status, daemon=True
            )
            zombie_check_thread.start()

        log("debug", "Running chat...")
        startup_phase = "running"
        chat.run()
    except Exception as e:
        details = traceback.format_exc()
        if startup_phase != "running":
            try:
                emit_message(
                    "startup_error",
                    phase=startup_phase,
                    message=str(e),
                    details=details,
                )
            except Exception:
                pass
        log("error", e, details)
        sys.exit(1)
