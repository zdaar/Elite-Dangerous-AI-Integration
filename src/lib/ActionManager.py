from hashlib import md5
from collections.abc import Iterator
from dataclasses import dataclass
import json
import random
import re
from typing import Any, Callable, Literal
import unicodedata

from openai.types.chat import ChatCompletionMessageFunctionToolCall
from pydantic import BaseModel


from .Database import KeyValueStore
from .Logger import log
import traceback

# Type alias for projected states dictionary
ProjectedStates = dict[str, BaseModel]


@dataclass(frozen=True)
class ActionRoutingDecision:
    action: ChatCompletionMessageFunctionToolCall | None
    reason: str | None = None
    cacheable: bool = True


class ActionManager:
    _MANAGED_GUIDE_ACTIONS = {
        "lookup_elite_guide",
    }
    _EXTERNAL_LOOKUP_ACTIONS = {
        "web_search_agent",
        "remember_memories",
    }
    _LOOKUP_ACTIONS = _MANAGED_GUIDE_ACTIONS | _EXTERNAL_LOOKUP_ACTIONS
    _EXPEDITION_REPLACEMENT_ACTIONS = {
        "find_exobiology_targets",
        "plan_tectonicas_expedition",
    }

    _CURRENT_CONTEXT_PATTERNS = tuple(re.compile(pattern) for pattern in (
        r"\bguide moi\b",
        r"\bguide me\b",
        r"\bwhat (?:do i do )?now\b",
        r"\bwhat next\b",
        r"\bque faire\b",
        r"\bquoi faire\b",
        r"\bqu est ce que je fais\b",
        r"\b(?:where|ou)\b.{0,30}\b(?:land|atterrir|look|chercher)\b",
        r"\b(?:how|comment)\b.{0,30}\b(?:find|trouver|scan|scanner|sample|echantillon)\b",
        r"\b(?:current|actuel|actuelle)\b.{0,12}\b(?:body|corps|planet|planete|target|cible)\b",
        r"\b(?:status|statut|progress|progression)\b.{0,24}\b(?:route|navigation|expedition|file|queue|index|target|cible|body|corps|planet|planete)\b",
        r"\b(?:route|navigation|expedition|file|queue|index|target|cible|body|corps|planet|planete)\b.{0,24}\b(?:status|statut|progress|progression)\b",
        r"\b(?:my|mon|ma|mes|our|notre)\b.{0,16}\b(?:status|statut|progress|progression)\b",
        r"\b(?:what|quel|quelle)\b.{0,12}\bindex\b",
    ))

    _CURRENT_BODY_DIRECT_PATTERNS = tuple(re.compile(pattern) for pattern in (
        r"\bguide moi\b.{0,60}\b(?:ici|sur ce|dans ce|dans le systeme|corps|planete)\b",
        r"\bguide me\b.{0,60}\b(?:here|on this|in this|body|planet|system)\b",
        r"\bwhat (?:do i do )?now\b",
        r"\bwhat next\b",
        r"\bque faire\b",
        r"\bquoi faire\b",
        r"\bqu est ce que je fais\b",
        r"\b(?:current|actuel|actuelle)\b.{0,12}\b(?:body|corps|planet|planete|target|cible)\b",
        r"\b(?:status|statut|progress|progression)\b.{0,24}\b(?:route|navigation|expedition|file|queue|index|target|cible|body|corps|planet|planete)\b",
        r"\b(?:route|navigation|expedition|file|queue|index|target|cible|body|corps|planet|planete)\b.{0,24}\b(?:status|statut|progress|progression)\b",
        r"\b(?:my|mon|ma|mes|our|notre)\b.{0,16}\b(?:status|statut|progress|progression)\b",
        r"\b(?:what|quel|quelle)\b.{0,12}\bindex\b",
    ))

    _EXPLICIT_ADVANCE_PATTERNS = tuple(re.compile(pattern) for pattern in (
        r"^(?:nova\s+)?(?:operation\s+)?next(?:\s+(?:target|cible))?$",
        r"^(?:nova\s+)?(?:skip|advance)$",
        r"\boperation\s+next\b",
        r"\b(?:next target|prochaine cible|cible suivante)\b",
        r"\b(?:advance|avance|skip|saute|abandonne)\b.{0,30}\b(?:target|cible|body|corps|queue|file)\b",
        r"\b(?:nothing|rien)(?:\s+is)?\s+(?:here|ici)\b",
        r"\b(?:done|finished|complete|termine|fini)\s+(?:here|ici)\b",
    ))

    _EXPLICIT_REPLAN_PATTERNS = tuple(re.compile(pattern) for pattern in (
        r"\b(?:create|build|plan|replan|cree|construis|planifie|replanifie|refais)\b.{0,40}\b(?:expedition|route|queue|file|target|cible)\b",
        r"\b(?:find|cherche|trouve)\b.{0,40}\b(?:profitable|rentable|money|credit|credits|tectonicas|stratum)\b",
        r"\b(?:new|nouveau|nouvelle|remplace|replace)\b.{0,24}\b(?:target|cible|expedition|route|queue|file)\b",
    ))

    _DIRECT_REQUEST_PATTERNS = tuple(re.compile(pattern) for pattern in (
        r"\b(?:call|appelle|use|utilise|execute)\b.{0,50}\b(?:tool|outil|action)\b",
        r"^(?:nova\s+)?(?:plot|replot|trace|retrace|ouvre|open|ferme|close|selectionne|select|definis|set|mets|reset|reinitialise)\b",
        r"\b(?:plot|replot|trace|retrace)\b.{0,40}\b(?:route|systeme|system|cible|target)\b",
        r"\b(?:how many|combien de)\b.{0,16}\b(?:jump|jumps|saut|sauts)\b",
        r"\b(?:where am i|ou suis je|systeme actuel|current system|cible actuelle|current target)\b",
        r"\b(?:statut|status)\b.{0,20}\b(?:route|navigation|expedition|file|queue|index)\b",
        r"\b(?:operation|index)\b.{0,20}\b(?:start|status|next|previous|reset|set|demarre|suivant|precedent)\b",
    ))

    @staticmethod
    def clear_action_cache():
        """clear action cache"""
        action_cache: KeyValueStore = KeyValueStore("action_cache")
        action_cache.delete_all()
    
    actions = {}

    def __init__(self):
        self.action_cache = KeyValueStore("action_cache")
        self.allowed_actions: dict[str, bool] = {}

    @staticmethod
    def _normalize_routing_text(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", str(value or ""))
        without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
        return " ".join(re.sub(r"[^a-z0-9_]+", " ", without_accents.casefold()).split())

    @classmethod
    def _matches_any(cls, text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @classmethod
    def _explicitly_requests_action(cls, text: str, action_name: str) -> bool:
        compact_text = text.replace("_", "").replace(" ", "")
        compact_name = cls._normalize_routing_text(action_name).replace("_", "").replace(" ", "")
        if compact_name and compact_name in compact_text:
            return True
        if action_name == "web_search_agent":
            return bool(re.search(r"\b(?:web search|search the web|recherche web|cherche sur le web)\b", text))
        if action_name == "remember_memories":
            return bool(re.search(r"\b(?:memory search|search memor|recherche memoire|cherche.*memoire)\b", text))
        if action_name == "lookup_elite_guide":
            return bool(re.search(r"\b(?:lookup|consulte|consult)\b.{0,24}\b(?:guide|doc)\b", text))
        return False

    @classmethod
    def _is_direct_request(cls, text: str, sibling_action_names: set[str]) -> bool:
        if any(name not in cls._LOOKUP_ACTIONS for name in sibling_action_names):
            return True
        compact_text = text.replace("_", "").replace(" ", "")
        for action_name in cls.actions:
            if action_name in cls._LOOKUP_ACTIONS:
                continue
            compact_name = cls._normalize_routing_text(action_name).replace("_", "").replace(" ", "")
            if compact_name and compact_name in compact_text:
                return True
        return (
            cls._matches_any(text, cls._DIRECT_REQUEST_PATTERNS)
            or cls._matches_any(text, cls._CURRENT_BODY_DIRECT_PATTERNS)
        )

    @classmethod
    def guard_action(
        cls,
        action: ChatCompletionMessageFunctionToolCall,
        latest_user_input: str,
        sibling_action_names: set[str] | None = None,
    ) -> ActionRoutingDecision:
        """Apply deterministic safety rules to model-selected actions.

        The model still chooses normal tools. This guard only neutralizes two
        known destructive routing mistakes: advancing or replacing an
        exobiology queue in response to local guidance, and doing a
        preliminary lookup before an explicit action or live-status request.
        """
        text = cls._normalize_routing_text(latest_user_input)
        action_name = action.function.name
        sibling_names = sibling_action_names or {action_name}

        if action_name == "control_exobiology_expedition":
            try:
                arguments = json.loads(action.function.arguments or "{}")
            except (TypeError, ValueError):
                arguments = {}
            if (
                isinstance(arguments, dict)
                and arguments.get("operation") == "next"
                and cls._matches_any(text, cls._CURRENT_CONTEXT_PATTERNS)
                and not cls._matches_any(text, cls._EXPLICIT_ADVANCE_PATTERNS)
            ):
                guarded_action = action.model_copy(deep=True)
                guarded_arguments = dict(arguments)
                guarded_arguments["operation"] = "status"
                guarded_action.function.arguments = json.dumps(guarded_arguments, ensure_ascii=False)
                return ActionRoutingDecision(
                    action=guarded_action,
                    reason="current-body guidance cannot advance the expedition; converted next to status",
                    cacheable=False,
                )

        if (
            action_name in cls._EXPEDITION_REPLACEMENT_ACTIONS
            and cls._matches_any(text, cls._CURRENT_CONTEXT_PATTERNS)
            and not cls._matches_any(text, cls._EXPLICIT_REPLAN_PATTERNS)
            and not cls._explicitly_requests_action(text, action_name)
        ):
            return ActionRoutingDecision(
                action=None,
                reason="current-body guidance cannot create or replace expedition targets",
                cacheable=False,
            )

        if (
            action_name in cls._LOOKUP_ACTIONS
            and cls._is_direct_request(text, sibling_names)
            and not cls._explicitly_requests_action(text, action_name)
        ):
            return ActionRoutingDecision(
                action=None,
                reason="preliminary lookup blocked for an explicit action or live-status request",
                cacheable=False,
            )

        if (
            action_name in cls._EXTERNAL_LOOKUP_ACTIONS
            and bool(sibling_names & cls._MANAGED_GUIDE_ACTIONS)
            and not cls._explicitly_requests_action(text, action_name)
        ):
            return ActionRoutingDecision(
                action=None,
                reason="external lookup blocked because the managed Elite guide is authoritative",
                cacheable=False,
            )

        return ActionRoutingDecision(action=action)

    def set_allowed_actions(self, allowed_actions: dict[str, bool] | None):
        """Set enabled states by permission key. Missing keys are disabled."""
        self.allowed_actions = allowed_actions if isinstance(allowed_actions, dict) else {}

    def getToolsList(self, active_mode: str, uses_actions: bool, uses_web_actions: bool, uses_ui_actions: bool, allowed_actions: dict[str, bool] | None = None):
        """return list of functions as passed to gpt"""

        actions = self.actions.values()
        valid_actions = []
        action_permissions = allowed_actions if isinstance(allowed_actions, dict) else {}
        for action in actions:
            permission_key = action.get("permission")
            if permission_key and action_permissions.get(permission_key) is not True:
                continue
            if uses_actions:
                # enable correct actions for game mode
                if action.get("type") == active_mode:
                    valid_actions.append(action.get("tool"))
                # enable correct actions for extended game mode
                elif active_mode == 'mainship' or active_mode == 'fighter':
                    if action.get("type") == 'ship':
                        valid_actions.append(action.get("tool"))
                # enable vision capabilities
                if action.get("type") == 'global':
                    valid_actions.append(action.get("tool"))
            if uses_web_actions:
                # enable web tools
                if action.get("type") == 'web':
                    valid_actions.append(action.get("tool"))

            if uses_ui_actions:
                if action.get("type") == 'ui':
                    valid_actions.append(action.get("tool"))

        return valid_actions
    
    def getActionDesc(self, tool_call: ChatCompletionMessageFunctionToolCall, projected_states: ProjectedStates):
        """ summarize functions input as text """
        if tool_call.function.name in self.actions:
            action_descriptor = self.actions.get(tool_call.function.name)
            function_args = json.loads(tool_call.function.arguments if tool_call.function.arguments else "null")
            input_template = action_descriptor.get("input_template")
            if input_template:
                input_desc = input_template(function_args, projected_states)
                # filter all duplicate whitespaces
                input_desc = ' '.join(input_desc.split())
                return input_desc
        return None
    

    def runAction(
        self,
        tool_call: ChatCompletionMessageFunctionToolCall,
        projected_states: ProjectedStates,
        processing_callback: Callable[[str, str, object], None] | None = None,
    ):
        """get function response and fetch matching python function, then call function using arguments provided"""
        function_result = None

        function_name = tool_call.function.name
        function_descriptor = self.actions.get(function_name)
        if function_descriptor:
            function_to_call = function_descriptor.get("method")
            function_args = json.loads(tool_call.function.arguments if tool_call.function.arguments else "null")

            try:
                function_result = function_to_call(function_args, projected_states)
                if isinstance(function_result, Iterator):
                    final_result: Any = None
                    while True:
                        try:
                            processing_result = next(function_result)
                        except StopIteration as stop:
                            final_result = stop.value
                            break
                        if processing_callback:
                            processing_callback(tool_call.id, function_name, processing_result)
                    function_result = final_result
            except Exception as e:
                log("debug", "An error occurred during function:", e, traceback.format_exc())
                function_result = "ERROR: " + repr(e)
        else:
            function_result = f"ERROR: Function {function_name} does not exist!"

        return {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": function_name,
            "content": function_result,
        }

    # register function
    def registerAction(
        self, name, description, parameters, 
        method: Callable[[dict, dict], object], 
        action_type="ship", 
        permission: str | None = None,
        input_template: Callable[[dict, dict], str] | None = None, 
        cache_prefill: dict[str, dict] | None = None
    ):
        """
            register action with name, description, parameters and method
            input_template is a function that takes the function arguments and projected states and returns a string
            cache_prefill is a dictionary of user input and arguments to prefill the cache with
        """
        if permission and self.allowed_actions.get(permission) is not True:
            log("debug", f"Action '{name}' skipped registration due to missing permission '{permission}'")
            return

        self.actions[name] = {
            "method": method,
            "type": action_type,
            "permission": permission,
            "input_template": input_template,
            "tool": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        }
        if cache_prefill is not None:
            for user_input, arguments in cache_prefill.items():
                #log('debug', 'Cache: prefilling', name, user_input, arguments)
                self.prefill_action_in_cache(user_input, ChatCompletionMessageFunctionToolCall(
                    type="function",
                    id=str(random.randint(100000, 999999)),
                    function={  # pyright: ignore[reportArgumentType]
                        "name": name,
                        "description": description,
                        "arguments": json.dumps(arguments)
                    }
                ), self.actions[name].get("tool"))

    def clean_user_input(self, user_input: str) -> str:
        """
            clean user input, remove whitespaces, convert to lowercase, remove all symbols
        """
        user_input = user_input.lower().strip()
        user_input = ''.join(e for e in user_input if e.isalnum())
        return user_input

    def hash_action_input(self, user_input: str, tool: dict) -> str:
        """
            hash user input
        """
        user_input = self.clean_user_input(user_input)
        return md5(json.dumps([user_input, tool]).encode()).hexdigest()

    def predict_action(self, user_input: str, tool_list) -> list[ChatCompletionMessageFunctionToolCall] | None:
        """
            predict action based on user input and available tools
        """
        # get the hash for user input with each tool
        input_hashes = [self.hash_action_input(user_input, tool) for tool in tool_list]
        # check if any of the input hashes match the predicted actions
        for input_hash in input_hashes:
            prediction = self.action_cache.get(input_hash)
            if prediction is not None and prediction.get("status") == "confirmed":
                # if prediction is confirmed, return the tool call
                new_id = str(random.randint(100000, 999999))
                tool_call = ChatCompletionMessageFunctionToolCall(
                    type="function",
                    id=new_id,
                    function=prediction.get("function")
                )
                log("debug", f"Cache: Action prediction found in cache with hash {input_hash}, returning tool call {new_id}")
                return [tool_call]
                
        return None

    def suggest_action_for_cache(self, user_input: str, action: ChatCompletionMessageFunctionToolCall, tool_list):
        """
            suggest action for cache
        """
        tool = None
        for t in tool_list:
            if t.get("function").get("name") == action.function.name:
                tool = t
                break
        
        if tool is None:
            log("debug", "Cache: No tool found for action suggestion")
            return
        
        # check if action is already in cache
        input_hash = self.hash_action_input(user_input, tool)
        if self.action_cache.get(input_hash) is not None:
            #log("debug", "Cache: Action already in cache")
            return
        
        # add action to cache
        self.action_cache.set(input_hash, {
            "status": "pending",
            "input": user_input,
            "function": {
                "name": action.function.name,
                "arguments": action.function.arguments
            }
        })
        log("info", f"Cache: Action {action.function.name} suggested for cache with hash {input_hash}")
    
    def confirm_action_in_cache(self, user_input: str, action: ChatCompletionMessageFunctionToolCall, tool_list):
        """
            confirm action in cache
        """
        tool = None
        for t in tool_list:
            if t.get("function").get("name") == action.function.name:
                tool = t
                break
        
        if tool is None:
            log("debug", "Cache: No tool found for action confirmation")
            return
        
        # check if action is already in cache
        input_hash = self.hash_action_input(user_input, tool)
        suggested_action = self.action_cache.get(input_hash)
        if suggested_action is None:
            log("debug", "Cache: Action not in cache, cannot confirm")
            return

        if suggested_action.get("function") != action.function.model_dump():
            log("debug", "Cache: Suggested action function does not match")
            self.action_cache.delete(input_hash)
            log("debug", "Cache: Deleted action from cache due to mismatch")
            return

        # update action in cache
        self.action_cache.set(input_hash, {
            "status": "confirmed",
            "input": user_input,
            "function": {
                "name": action.function.name,
                "arguments": action.function.arguments
            }
        })
        log("info", f"Cache: Action {action.function.name} confirmed in cache with hash {input_hash}")

    def prefill_action_in_cache(self, user_input: str, action: ChatCompletionMessageFunctionToolCall, tool):
        """
            prefill action cache with user input and action
        """
        input_hash = self.hash_action_input(user_input, tool)
        if self.action_cache.get(input_hash) is not None:
            #log("debug", "Cache: Action already in cache, skipping prefill")
            return
        
        # add action to cache
        self.action_cache.set(input_hash, {
            "status": "confirmed",
            "input": user_input,
            "function": {
                "name": action.function.name,
                "arguments": action.function.arguments
            }
        })
        log("info", f"Cache: Action {action.function.name} prefilled in cache with hash {input_hash}")

    def has_action_in_cache(self, user_input: str, action: ChatCompletionMessageFunctionToolCall, tool_list) -> Literal["suggested", "confirmed", False]:
        """
            check if there is a suggested action in cache
        """
        tool = None
        for t in tool_list:
            if t.get("function").get("name") == action.function.name:
                tool = t
                break

        if tool is None:
            log("debug", "Cache: No tool found for action suggestion")
            return False

        input_hash = self.hash_action_input(user_input, tool)
        if self.action_cache.get(input_hash) is not None:
            return self.action_cache.get(input_hash).get("status")
        log("debug", "Cache: No suggested action found in cache")
        return False
