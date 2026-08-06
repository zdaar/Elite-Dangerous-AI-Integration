import json
import os
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lib.PluginBase import PluginBase, PluginManifest
from lib.PluginHelper import PluginHelper
from lib.actions.ExobiologyPlanner import plan_exobiology


class PlannerParameters(BaseModel):
    strategy: Literal["auto", "stratum_sniping", "throughput", "first_discovery"] = "auto"
    radius: int | None = Field(default=None, ge=25, le=5000)
    max_results: int = Field(default=8, ge=1, le=20)
    max_arrival_ls: int = Field(default=1700, ge=100, le=100000)


class FieldGuideParameters(BaseModel):
    genuses: list[str] = Field(description="Biological genera shown by the Detailed Surface Scanner filters")


class GuideLookupParameters(BaseModel):
    query: str = Field(min_length=3, description="The exact Elite Dangerous mechanics question to verify")
    max_chunks: int = Field(default=5, ge=1, le=8)


class TectonicasExpeditionParameters(BaseModel):
    max_systems: int = Field(default=10, ge=1, le=20)
    search_radius_ly: int = Field(default=500, ge=25, le=5000)
    max_arrival_ls: int = Field(default=1700, ge=100, le=100000)


class ExpeditionControlParameters(BaseModel):
    operation: Literal["start", "next", "status", "previous", "reset", "set"] = "status"
    index: int | None = Field(
        default=None,
        description="One-based queue index. Required only when operation is set.",
    )
    plot: bool = Field(
        default=True,
        description="When operation is set, plot/select the chosen target immediately.",
    )


FRENCH_SEARCH_TERMS = {
    "chercher": "find locate search", "trouver": "find locate", "atterrir": "land landing terrain",
    "échantillon": "sample sampling genetic sampler", "echantillon": "sample sampling genetic sampler",
    "scanner": "scan scanner pulse DSS", "distance": "distance separation colony range",
    "valeur": "value credits payout", "combinaison": "suit Artemis", "planète": "planet body",
    "planete": "planet body", "espèce": "species organism genus", "espece": "species organism genus",
    "première découverte": "first discovery bonus first logged", "premiere decouverte": "first discovery bonus first logged",
    "route": "route routing", "vendre": "sell Vista Genomics", "filtre": "filter DSS overlay",
    "commande": "command say phrase voiceattack", "demander": "request", "amarrage": "docking dock",
    "réparer": "fix repair diagnostics", "reparer": "fix repair diagnostics",
    "onglet": "tab panel diagnostics desync", "désynchron": "desync diagnostics panel tracking",
    "desynchron": "desync diagnostics panel tracking", "poste": "station crew roster assign",
    "tous": "all take all stations", "affecter": "assign crewman station", "mettre": "assign set",
    "station d'exploration": "science officer scanning crew station",
}


FIELD_GUIDE = {
    "stratum": {"priority": 1, "terrain": "flat, open plains inside the Stratum overlay; avoid broken ground", "appearance": "broad layered mats or low plate-like colonies", "method": "Use the DSS Stratum filter to find compatible terrain, then fly low over flat areas and land with long clear sight-lines. Overlay brightness or colour intensity does not indicate organism density."},
    "clypeus": {"priority": 2, "terrain": "rocky slopes and rough highlands, not flat plains", "appearance": "large upright fan/shell structures", "method": "Use the Clypeus filter; search illuminated rocky slopes from the ship or SRV."},
    "tussock": {"priority": 5, "terrain": "open plains and gentle slopes", "appearance": "small grass-like clumps", "method": "Use the Tussock filter; low-altitude visual search or SRV because individual clumps are small."},
    "frutexa": {"priority": 4, "terrain": "rocky ground, slopes and foothills", "appearance": "bushy branching shrubs", "method": "Use the Frutexa filter; scan rough foothills rather than smooth plains."},
    "osseus": {"priority": 3, "terrain": "rocky and mountainous ground", "appearance": "pale branching bone/coral-like growths", "method": "Use the Osseus filter; search rock fields and mountain bases."},
    "fungoida": {"priority": 6, "terrain": "mountainous, rocky terrain and crater slopes", "appearance": "mushroom-like caps or stalked colonies", "method": "Use the Fungoida filter; search rugged slopes, accepting slower travel only after higher-value genera."},
    "cactoida": {"priority": 7, "terrain": "rocky plains and slopes", "appearance": "upright cactus-like columns or clusters", "method": "Use the Cactoida filter and fly low across moderately rough ground."},
    "bacterium": {"priority": 8, "terrain": "flat ground matching its colour; often low contrast", "appearance": "thin discoloured surface patches", "method": "Lowest priority here. Use the DSS Bacterium filter, then search from higher altitude with the external camera and low-angle light; turn night vision off because Bacterium does not render under it. Skip if search time damages credits/hour."},
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _state(context: dict[str, Any], name: str) -> dict[str, Any]:
    value = context.get(name)
    if value is None:
        value = context.get(name.casefold())
    return _as_dict(value)


def _systems_match(first: Any, second: Any) -> bool:
    return bool(
        str(first or "").strip()
        and str(first or "").strip().casefold() == str(second or "").strip().casefold()
    )


def _route_system(entry: Any) -> str | None:
    item = _as_dict(entry)
    value = item.get("StarSystem") or item.get("star_system")
    text = str(value or "").strip()
    return text or None


def _navigation_truth(target: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    target_system = str(target.get("system") or "").strip() or None
    current_system = str(
        _state(context, "Location").get("StarSystem")
        or _state(context, "Location").get("star_system")
        or ""
    ).strip() or None
    nav_info = _state(context, "NavInfo")
    route = nav_info.get("NavRoute") or []
    if not isinstance(route, list):
        route = []
    route_next_hop = _route_system(route[0]) if route else None
    route_destination = _route_system(route[-1]) if route else None
    target_reached = bool(
        target_system and current_system and _systems_match(current_system, target_system)
    )
    route_verified = bool(
        target_system and route_destination and _systems_match(route_destination, target_system)
    )
    if target_reached:
        navigation_state = "already_in_target_system"
    elif route_verified:
        navigation_state = "verified_route_to_target"
    elif target_system and route_destination:
        navigation_state = "route_target_mismatch"
    else:
        navigation_state = "no_verified_route"
    return {
        "current_system": current_system,
        "target_system": target_system,
        "target_reached": target_reached,
        "route_verified": route_verified,
        "navigation_verified": target_reached or route_verified,
        "navigation_state": navigation_state,
        "route_next_hop": route_next_hop,
        "route_destination": route_destination,
        "remaining_jumps": len(route),
        "next_jump_target": nav_info.get("NextJumpTarget"),
    }


def _plot_result_payload(
    result: Any,
    requested: dict[str, Any],
    target: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Convert the built-in plotter's text contract into truthful state."""
    result_text = str(result)
    lowered = result_text.casefold()
    target_system = str(target.get("system") or "").strip()
    target_body = str(target.get("body") or "").strip() or None
    current_system = str(_state(context, "Location").get("StarSystem") or "").strip()
    navigation = _navigation_truth(target, context)
    route_destination = navigation["route_destination"]

    success = False
    verified = False
    status = "unverified_result"
    failure_markers = (
        "failed to plot",
        "could not plot",
        "cannot plot",
        "error executing action",
        "plot target is unavailable",
        "plot action raised",
    )
    if any(marker in lowered for marker in failure_markers):
        status = "plot_failed"
    elif (
        "successfully plotted" in lowered
        and f"route to {target_system}".casefold() in lowered
    ):
        # Plotter emits this only after NavInfo reports the exact final system.
        success = True
        verified = True
        status = "route_plotted"
    elif (
        "route to" in lowered
        and "already set" in lowered
        and target_system.casefold() in lowered
    ):
        success = True
        verified = True
        status = "route_already_set"
    elif requested.get("body") and _systems_match(current_system, target_system):
        if "in-system navigation" in lowered and (
            "completed" in lowered or "configured" in lowered
        ):
            success = True
            verified = True
            status = "body_selected"
        elif "is in the current system already" in lowered:
            # Resolution succeeded, but in-system selection is disabled. Do
            # not turn a lookup-only result into a successful navigation claim.
            verified = True
            status = "body_resolved_not_selected"
    elif (
        not requested.get("body")
        and _systems_match(current_system, target_system)
        and "already in" in lowered
    ):
        success = True
        verified = True
        status = "already_in_system"
    elif _systems_match(route_destination, target_system):
        # Retain useful route metadata, but do not override an unknown action
        # result. A stale context route is not proof this call succeeded.
        status = "matching_route_unverified_result"

    return {
        "success": success,
        "verified": verified,
        "status": status,
        "requested": requested,
        "target_system": target_system,
        "target_body": target_body,
        "route_destination": route_destination,
        "route_verified": navigation["route_verified"],
        "navigation_verified": navigation["navigation_verified"],
        "navigation_state": navigation["navigation_state"],
        "route_next_hop": navigation["route_next_hop"],
        "remaining_jumps": navigation["remaining_jumps"],
        "result": result_text,
    }


def _plan(parameters: PlannerParameters, context: dict[str, Any]) -> str:
    args = parameters.model_dump(exclude_none=True)
    plan = plan_exobiology(args, context)
    plan["next_action"] = (
        "Call plotToTarget for navigation_instruction immediately. For Stratum sniping, plot the system first; "
        "after arrival select or FSS-resolve only targeted_fss_bodies. Never run a full-system FSS. "
        "Verify the final live NavRoute entry exactly matches the requested system before reporting a successful route. "
        "Any distance_ly in this result is measured from the planning source, not a live remaining distance."
    )
    return json.dumps(plan, ensure_ascii=False)


def _expedition_queue(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten clustered system results without dropping any candidate body."""
    queue: list[dict[str, Any]] = []
    for system_index, system_target in enumerate(plan.get("targets") or [], start=1):
        system = str(system_target.get("system") or "").strip()
        bodies = system_target.get("bodies") or []
        if not bodies and system_target.get("body"):
            bodies = [{"body": system_target["body"]}]
        body_names = [
            str(body.get("body") or "").strip()
            for body in bodies
            if str(body.get("body") or "").strip()
        ]
        if not system or not body_names:
            continue
        for body_index, body in enumerate(bodies, start=1):
            body_name = str(body.get("body") or "").strip()
            if not body_name:
                continue
            queue.append({
                "system": system,
                "body": body_name,
                "system_queue_position": system_index,
                "body_queue_position": body_index,
                "body_count_in_system": len(body_names),
                "targeted_fss_bodies": body_names,
                "distance_to_arrival_ls": body.get("distance_to_arrival_ls"),
                "atmosphere": body.get("atmosphere"),
                "gravity_g": body.get("gravity_g"),
                "surface_temperature_k": body.get("surface_temperature_k"),
                "updated_at": body.get("updated_at"),
                "distance_ly": system_target.get("distance_ly"),
                "distance_from_planning_source_ly": system_target.get("distance_ly"),
                "distance_from_sol_ly": system_target.get("distance_from_sol_ly"),
                "estimated_jumps": system_target.get("estimated_jumps"),
                "route_order": system_target.get("route_order"),
                "confidence_tier": system_target.get("confidence_tier"),
                "confidence": system_target.get("confidence"),
                "instruction": (
                    f"In {system}, select {body_name} directly if it is exposed. Otherwise resolve only these HMC bodies in FSS: "
                    f"{', '.join(body_names)}. Stop after the listed bodies; do not scan the rest of the system. "
                    "Check BioInsights, then DSS only if Stratum is predicted."
                ),
            })
    return queue


def _field_guide(parameters: FieldGuideParameters, _context: dict[str, Any]) -> str:
    selected = []
    for raw_name in parameters.genuses:
        key = raw_name.strip().casefold().replace("$codex_ent_", "").replace("_genus_name;", "")
        key = {"fungoids": "fungoida", "cactoids": "cactoida", "bacterial": "bacterium", "shrubs": "frutexa", "tussocks": "tussock"}.get(key, key)
        guide = FIELD_GUIDE.get(key)
        if guide:
            selected.append({"genus": key.title(), **guide})
    selected.sort(key=lambda item: item["priority"])
    return json.dumps({
        "scope": "Current body only. Do not find another target or advance the expedition queue.",
        "sampling_order": selected,
        "immediate_instruction": (
            f"Select the {selected[0]['genus']} DSS filter and search {selected[0]['terrain']}. {selected[0]['method']}"
            if selected else "Read the genus names from the DSS filter list and call this tool again."
        ),
        "sampling_rule": "Collect three genetically diverse samples of the selected species before switching species; the required separation is species-specific and the sampler indicates validity.",
        "warning": "DSS colours show probable surface regions, not exact organism positions. Do not claim coordinates unless a tool supplied them.",
    }, ensure_ascii=False)


def _knowledge_root() -> Path | None:
    configured = os.environ.get("COVAS_ELITE_GUIDE_PATH")
    appdata = os.environ.get("APPDATA")
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    candidates: list[Path | None] = [
        # A caller-supplied override always wins.
        Path(configured).expanduser() if configured else None,
        # Production backend cwd and the normal Windows Electron userData path.
        Path.cwd() / "managed-guides" / "elite",
        Path(appdata) / "com.covas-next.ui" / "managed-guides" / "elite" if appdata else None,
        # Linux Electron userData fallback when no override was injected.
        Path(xdg_config_home) / "com.covas-next.ui" / "managed-guides" / "elite" if xdg_config_home else None,
        Path.home() / ".config" / "com.covas-next.ui" / "managed-guides" / "elite",
        # Source checkout fallback for development and tests.
        Path(__file__).resolve().parents[2] / "guides" / "elite",
        # Legacy user-managed locations retained for compatibility.
        Path.home() / "COVAS-Elite-Guide",
        Path(os.environ.get("USERPROFILE", "")) / "Claude" / "Projects" / "Elite Dangerous" / ".claude" / "skills"
        if os.environ.get("USERPROFILE") else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir():
            return candidate
    return None


def _chunks(text: str) -> list[str]:
    parts = re.split(r"(?=^#{1,4}\s+)", text, flags=re.MULTILINE)
    return [part.strip() for part in parts if len(part.strip()) >= 40]


def _guide_lookup(parameters: GuideLookupParameters, _context: dict[str, Any]) -> str:
    root = _knowledge_root()
    if root is None:
        return json.dumps({"verified": False, "reason": "Local Elite guide repository is unavailable. Do not answer from model knowledge."})
    expanded = parameters.query.casefold()
    for french, english in FRENCH_SEARCH_TERMS.items():
        if french in expanded:
            expanded += " " + english
    terms = {term for term in re.findall(r"[a-zà-ÿ0-9]{3,}", expanded) if term not in {"the", "and", "pour", "avec", "dans", "une", "des", "les", "que", "quoi", "comment"}}
    matches = []
    for path in root.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for chunk in _chunks(text):
            lowered = chunk.casefold()
            present_terms = [term for term in terms if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)]
            score = sum(4 if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered[:240]) else 2 if f"`{term}" in lowered else 1 for term in present_terms)
            if "| say | does |" in lowered:
                score += 3
            if "/references/" in f"/{path.relative_to(root)}".replace("\\", "/"):
                score += 2
            if score:
                matches.append((score, str(path.relative_to(root)), chunk[:2400]))
    matches.sort(key=lambda item: (-item[0], len(item[2])))
    evidence = [{"source": source, "content": content} for _, source, content in matches[:parameters.max_chunks]]
    return json.dumps({
        "verified": bool(evidence),
        "question": parameters.query,
        "evidence": evidence,
        "response_contract": (
            "Answer only with facts explicitly present in evidence and cite the source filename orally only if useful. "
            "Do not add model knowledge, conversational memory, inferred controls, coordinates, or roleplay. "
            "If evidence is insufficient, say 'Guide local insuffisant' and perform at most one sourced search. "
            "This guide is for explanations only; never use its result to claim current route, scan, queue, target, or distance state."
        ),
    }, ensure_ascii=False)


class ExobiologyProfitPlannerPlugin(PluginBase):
    def __init__(self, plugin_manifest: PluginManifest):
        super().__init__(plugin_manifest)
        self._helper: PluginHelper | None = None
        self._expedition_file: Path | None = None

    def _load_expedition(self) -> dict[str, Any] | None:
        if self._expedition_file is None or not self._expedition_file.exists():
            return None
        try:
            return json.loads(self._expedition_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save_expedition(self, expedition: dict[str, Any]) -> None:
        if self._expedition_file is None:
            raise RuntimeError("Expedition storage is unavailable")
        self._expedition_file.write_text(json.dumps(expedition, ensure_ascii=False, indent=2), encoding="utf-8")

    def _plot_expedition_target(self, target: dict[str, Any], context: dict[str, Any]) -> Any:
        if self._helper is None:
            raise RuntimeError("Plugin helper is unavailable")
        descriptor = self._helper._action_manager.actions.get("plotToTarget")
        if not descriptor:
            raise RuntimeError("plotToTarget is unavailable or disabled")
        plot_args = {"system": target["system"]}
        current_system = str(
            _state(context, "Location").get("StarSystem")
            or _state(context, "Location").get("star_system")
            or ""
        ).strip()
        target_system = str(target.get("system") or "").strip()
        body = str(target.get("body") or "").strip()
        if body and current_system.casefold() == target_system.casefold():
            # The built-in plotter safely gates in-system body selection on its
            # navigation capability. Outside the target system, plotting the
            # system alone avoids trying to select an unreachable body.
            plot_args["body"] = body
        try:
            result = descriptor["method"](plot_args, context)
        except Exception as error:
            result = f"Plot action raised: {error}"
        return _plot_result_payload(result, plot_args, target, context)

    def _expedition_status(self, states: dict[str, Any]) -> list[tuple[str, Any]]:
        expedition = self._load_expedition()
        if not expedition or not expedition.get("targets"):
            return []
        index = int(expedition.get("index", 0))
        targets = expedition["targets"]
        current = targets[index] if 0 <= index < len(targets) else None
        current_system = str(_state(states, "Location").get("StarSystem") or "").strip() or None
        target_system = str(current.get("system") or "").strip() if current else None
        navigation = _navigation_truth(current or {}, states)
        return [("Active exobiology expedition", {
            "strategy": expedition.get("strategy"),
            "queue_index": index + 1 if current else None,
            "queue_progress": f"{index + 1}/{len(targets)}" if current else "complete",
            "planning_source_system": expedition.get("source_system"),
            "current_system": current_system,
            "target_system": target_system,
            "target_body": current.get("body") if current else None,
            "distance_from_planning_source_ly": (
                current.get("distance_from_planning_source_ly", current.get("distance_ly")) if current else None
            ),
            "targeted_fss_bodies": current.get("targeted_fss_bodies", []) if current else [],
            "navigation_verified": navigation["navigation_verified"],
            "route_verified": navigation["route_verified"],
            "navigation_state": navigation["navigation_state"],
            "route_next_hop": navigation["route_next_hop"],
            "route_destination": navigation["route_destination"],
            "remaining_jumps": navigation["remaining_jumps"],
            "next_jump_target": navigation["next_jump_target"],
            "instruction": current.get("instruction") if current else "Queue complete.",
            "distance_rule": (
                "The stored distance is from the planning source, not the ship's current distance. "
                "Use only a live calculation for current distance."
            ),
            "route_rule": (
                "route_next_hop is the first live route entry; route_destination is the final live route entry. "
                "Do not call a route successful when navigation_state is route_target_mismatch or no_verified_route."
            ),
            "control": (
                "Use control_exobiology_expedition: status reads; start replots without advancing; next/previous move one; "
                "set selects a one-based index; reset only on explicit request. Set plot=false for queue-only changes."
            ),
        })]

    def _plan_tectonicas_expedition(self, parameters: TectonicasExpeditionParameters, context: dict[str, Any]) -> str:
        plan = plan_exobiology({
            "strategy": "stratum_sniping",
            "radius": parameters.search_radius_ly,
            "max_results": parameters.max_systems,
            "max_arrival_ls": parameters.max_arrival_ls,
        }, context)
        queue = _expedition_queue(plan)
        if not queue:
            return json.dumps({
                "success": False,
                "reason": (
                    "No compatible pre-Odyssey HMC records were returned under the current radius and arrival cap. "
                    "This does not prove the area has no biology."
                ),
                "strategy": plan.get("strategy"),
                "search_center_coords": plan.get("search_center_coords"),
            }, ensure_ascii=False)
        expedition = {
            "version": 2,
            "strategy": "stratum_sniping",
            "source_system": plan.get("source_system"),
            "source_coords": plan.get("source_coords"),
            "jump_range": plan.get("jump_range"),
            "radius_ly": plan.get("radius_ly"),
            "max_arrival_ls": plan.get("max_arrival_ls"),
            "outward_staging_applied": plan.get("outward_staging_applied"),
            "system_count": len(plan.get("targets") or []),
            "index": 0,
            "targets": queue,
            "created_at": time.time(),
        }
        self._save_expedition(expedition)
        plot_result = self._plot_expedition_target(queue[0], context)
        return json.dumps({
            "success": plot_result["success"],
            "plan_saved": True,
            "route_verified": plot_result["route_verified"],
            "navigation_verified": plot_result["navigation_verified"],
            "navigation_state": plot_result["navigation_state"],
            "strategy": expedition["strategy"],
            "systems": expedition["system_count"],
            "body_queue_size": len(queue),
            "current_target": queue[0],
            "targeted_fss_bodies": queue[0]["targeted_fss_bodies"],
            "plot_result": plot_result,
            "instruction": queue[0]["instruction"],
            "control": (
                "Say prochaine cible / next target to advance one exact body; use operation=set with a one-based index "
                "to select an explicit queue position."
            ),
            "warning": (
                "First Footfall is a surface marker and pays no bonus. The 5x bonus requires First Logged when the data is first sold. "
                "A stale pre-Odyssey record guarantees neither."
            ),
        }, ensure_ascii=False)

    def _control_expedition(self, parameters: ExpeditionControlParameters, context: dict[str, Any]) -> str:
        expedition = self._load_expedition()
        if not expedition or not expedition.get("targets"):
            return json.dumps({"success": False, "reason": "No active expedition. Call plan_tectonicas_expedition first."})
        targets = expedition["targets"]
        stored_index = int(expedition.get("index", 0))
        index = stored_index
        if parameters.operation == "reset":
            expedition["index"] = 0
            self._save_expedition(expedition)
            return json.dumps({
                "success": True,
                "queue_updated": stored_index != 0,
                "queue_index": 1,
                "queue_progress": f"1/{len(targets)}",
                "current_target": targets[0],
                "targeted_fss_bodies": targets[0].get("targeted_fss_bodies", []),
                "instruction": targets[0].get("instruction"),
            }, ensure_ascii=False)

        if parameters.operation == "set":
            requested_index = parameters.index
            if requested_index is None:
                return json.dumps({
                    "success": False,
                    "queue_updated": False,
                    "reason": "operation=set requires a one-based index.",
                    "valid_index_range": {"min": 1, "max": len(targets)},
                    "current_index": stored_index + 1 if stored_index < len(targets) else None,
                }, ensure_ascii=False)
            if requested_index < 1 or requested_index > len(targets):
                return json.dumps({
                    "success": False,
                    "queue_updated": False,
                    "reason": f"Queue index {requested_index} is out of range.",
                    "requested_index": requested_index,
                    "valid_index_range": {"min": 1, "max": len(targets)},
                    "current_index": stored_index + 1 if stored_index < len(targets) else None,
                }, ensure_ascii=False)
            index = requested_index - 1
        elif parameters.operation == "next":
            index += 1
        elif parameters.operation == "previous":
            index = max(0, index - 1)
        if index >= len(targets):
            expedition["index"] = len(targets)
            self._save_expedition(expedition)
            return json.dumps({
                "success": True,
                "queue_updated": stored_index != len(targets),
                "complete": True,
                "message": "Target queue complete.",
            })

        queue_updated = index != stored_index
        if queue_updated:
            expedition["index"] = index
            self._save_expedition(expedition)
        target = targets[index]
        plot_result = None
        should_plot = parameters.operation in {"start", "next", "previous"} or (
            parameters.operation == "set" and parameters.plot
        )
        if should_plot:
            plot_result = self._plot_expedition_target(target, context)
        navigation = _navigation_truth(target, context)
        action_success = plot_result["success"] if plot_result is not None else True
        return json.dumps({
            "success": action_success,
            "queue_updated": queue_updated,
            "queue_index": index + 1,
            "queue_progress": f"{index + 1}/{len(targets)}",
            "current_system": _state(context, "Location").get("StarSystem"),
            "current_target": target,
            "targeted_fss_bodies": target.get("targeted_fss_bodies", []),
            "instruction": target.get("instruction"),
            "plot_requested": should_plot,
            "route_verified": navigation["route_verified"],
            "navigation_verified": navigation["navigation_verified"],
            "navigation_state": navigation["navigation_state"],
            "route_next_hop": navigation["route_next_hop"],
            "route_destination": navigation["route_destination"],
            "remaining_jumps": navigation["remaining_jumps"],
            "plot_result": plot_result,
        }, ensure_ascii=False)

    def on_chat_start(self, helper: PluginHelper):
        self._helper = helper
        self._expedition_file = Path(helper.get_plugin_data_path(self.plugin_manifest)) / "tectonicas-expedition.json"
        helper.register_status_generator(lambda _states: [("Authoritative Elite facts policy", {
            "rule": (
                "Use lookup_elite_guide only for explanatory questions about Elite mechanics or facts. "
                "Never call it before a direct action, navigation command, status read, or another concrete tool call."
            ),
            "action_priority": (
                "If the commander asks to plot, target, open, close, scan, navigate, control the ship, or use a named tool, "
                "call the relevant action immediately. Live state and successful tool output are already authoritative."
            ),
            "forbidden_sources": ["model training knowledge", "conversation memory", "prior assistant claims", "inference"],
            "allowed_sources": [
                "live state/context", "direct journal events", "successful tool output", "lookup_elite_guide evidence",
                "an explicit sourced search when local evidence is insufficient",
            ],
            "failure_response": "Information non vérifiée.",
            "style": (
                "Default to concise operation with no unsolicited roleplay. An explicit commander request for a joke, humour, "
                "roleplay, flirt, or another tone overrides that default for the requested exchange and must not be refused."
            ),
            "memory_rule": (
                "Conversation memory is historical context only. Never use it as current proof of a route, target, queue index, "
                "scan, body state, or distance."
            ),
            "route_failure_rule": (
                "A failed multi-jump plot never means the destination exceeds the ship's single-jump range. "
                "Report the exact failure only and do not guess at filters, UI focus, pathfinding, star density, or another cause."
            ),
            "first_logged_rule": (
                "First Footfall and a stale community record never prove First Logged availability. State confirmed base value; "
                "label 5x as potential until a sale event confirms it."
            ),
        })])
        helper.register_status_generator(self._expedition_status)
        if "find_exobiology_targets" not in helper._action_manager.actions:
            helper.register_action(
                name="find_exobiology_targets",
                description=(
                    "Immediately find and rank exobiology money targets from live location. Call this first for requests such as maximize "
                    "exobiology credits or find me profitable planets; do not run lookup_elite_guide, a web search, "
                    "or a status probe first. auto, stratum_sniping, and first_discovery use exact pre-Odyssey HMC body records as non-guaranteed "
                    "Stratum leads; throughput explicitly requests public confirmed organisms for reliable base-value routing. After a result, "
                    "call plotToTarget with navigation_instruction immediately. For Stratum sniping, honk and resolve only targeted_fss_bodies; "
                    "never request a full-system FSS. Treat distance_ly as distance from the planning source. Do not use this for current "
                    "route/queue status, direct navigation, or sampling organisms on the current body; do not fall back to a generic search."
                ),
                parameters=PlannerParameters,
                method=_plan,
                action_type="web",
                input_template=lambda args, _context: "Optimizing an exobiology route from the current system",
            )
        if "get_exobiology_field_guide" not in helper._action_manager.actions:
            helper.register_action(
                name="get_exobiology_field_guide",
                description=(
                    "Give concrete terrain, visual appearance, DSS-filter workflow, and profit-priority guidance for biological genera "
                    "already shown on the commander's current planet. Use when asked what to look for, where to land, or how to find a genus. "
                    "Stay on the current body: do not search for another planet, advance/reset the expedition, or invent exact coordinates."
                ),
                parameters=FieldGuideParameters,
                method=_field_guide,
                action_type="web",
                input_template=lambda args, _context: "Preparing an on-planet exobiology search order",
            )
        if "lookup_elite_guide" not in helper._action_manager.actions:
            helper.register_action(
                name="lookup_elite_guide",
                description=(
                    "Source-of-truth lookup for EXPLANATORY questions about Elite Dangerous mechanics, equipment, economy, navigation, "
                    "exploration, combat, engineering, or exobiology. Do not call this for a direct action request, a basic tool call, "
                    "a status request answerable from live context, a journal event, or data already returned by another tool. For direct "
                    "commands, call the requested ship/web action immediately without preliminary lookup or search."
                ),
                parameters=GuideLookupParameters,
                method=_guide_lookup,
                action_type="web",
                input_template=lambda args, _context: f"Consulting the verified Elite guide: {args.get('query', '')}",
            )
        if "plan_tectonicas_expedition" not in helper._action_manager.actions:
            helper.register_action(
                name="plan_tectonicas_expedition",
                description=(
                    "Immediately build and persist an efficient fixed queue from pre-Odyssey HMC Stratum leads when the commander asks Nova to "
                    "create a new managed expedition and plot targets one by one. Do not use it merely to inspect, resume, or change an existing "
                    "queue; use control_exobiology_expedition for that. Do not perform a guide lookup or web search first. Keep every exact candidate body in "
                    "clustered systems, then plot the first system. At each system, select exposed bodies directly or resolve only the listed HMC "
                    "bodies in FSS; never instruct a full-system scan. These are stale-record leads, not guarantees of Stratum, First Footfall, "
                    "or First Logged. First Footfall pays no bonus; First Logged is determined when biodata is first sold."
                ),
                parameters=TectonicasExpeditionParameters,
                method=self._plan_tectonicas_expedition,
                action_type="web",
                input_template=lambda args, _context: "Building a persistent outward Tectonicas expedition",
            )
        if "control_exobiology_expedition" not in helper._action_manager.actions:
            helper.register_action(
                name="control_exobiology_expedition",
                description=(
                    "Control the persistent exobiology expedition without a preliminary lookup or search. status reads without mutation; start "
                    "replots the current target; next/previous move one body; set selects the supplied one-based index; reset requires an explicit "
                    "reset request. Use plot=false for a queue-only set. Call next only for 'prochaine cible'/'next target' or explicit completion/skip; "
                    "'guide me here', 'what now?', and current-body questions must not advance. The result separates queue_updated from verified plot "
                    "success; report any requested-target/route-destination mismatch and never tell the commander to jump on a mismatch."
                ),
                parameters=ExpeditionControlParameters,
                method=self._control_expedition,
                action_type="ship",
                input_template=lambda args, _context: f"Exobiology expedition: {args.get('operation', 'status')}",
            )

    def on_chat_stop(self, helper: PluginHelper):
        pass
