import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lib.PluginBase import PluginBase, PluginManifest
from lib.PluginHelper import PluginHelper
from lib.Event import Event, GameEvent
from lib.RouteSafety import RouteSafetyPolicy, route_safety_policy_from_config
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


def _body_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _short_body_name(system: str, body: str) -> str:
    prefix = f"{system.strip()} "
    if body.casefold().startswith(prefix.casefold()):
        return body[len(prefix):].strip()
    return body.strip()


def _join_spoken(items: list[str], language: str) -> str:
    if len(items) < 2:
        return items[0] if items else ""
    conjunction = " et " if language == "fr" else " and "
    return f"{', '.join(items[:-1])}{conjunction}{items[-1]}"


def _candidate_bodies_in_visit_order(target: dict[str, Any]) -> list[str]:
    """Return exact candidate names ordered by arrival distance when available."""
    raw_names = [
        str(name or "").strip()
        for name in target.get("targeted_fss_bodies") or []
        if str(name or "").strip()
    ]
    records = {
        _body_key(record.get("body")): record
        for record in target.get("candidate_bodies") or []
        if isinstance(record, dict) and str(record.get("body") or "").strip()
    }

    def sort_key(item: tuple[int, str]) -> tuple[float, int]:
        original_index, name = item
        distance = records.get(_body_key(name), {}).get("distance_to_arrival_ls")
        if isinstance(distance, (int, float)):
            return float(distance), original_index
        return float("inf"), original_index

    return [name for _index, name in sorted(enumerate(raw_names), key=sort_key)]


def _biological_signal_count(content: dict[str, Any]) -> int:
    count = 0
    for signal in content.get("Signals") or []:
        if not isinstance(signal, dict):
            continue
        signal_type = str(signal.get("Type") or "").casefold()
        localised = str(signal.get("Type_Localised") or "").casefold()
        if "biological" not in signal_type and "biological" not in localised and "biologique" not in localised:
            continue
        raw_count = signal.get("Count", 0)
        if isinstance(raw_count, (int, float)):
            count += max(0, int(raw_count))
    return count


def _route_system(entry: Any) -> str | None:
    item = _as_dict(entry)
    value = item.get("StarSystem") or item.get("star_system")
    text = str(value or "").strip()
    return text or None


FUEL_STAR_CLASSES = frozenset({"K", "G", "B", "F", "O", "A", "M"})


def _star_position(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if any(not isinstance(coordinate, (int, float)) for coordinate in value):
        return None
    return float(value[0]), float(value[1]), float(value[2])


def _route_brief(target: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, ready-to-read summary from the live plotted route."""
    target_system = str(target.get("system") or "").strip()
    navigation = _navigation_truth(target, context)
    nav_info = _state(context, "NavInfo")
    raw_route = nav_info.get("NavRoute") or []
    route = [_as_dict(entry) for entry in raw_route] if isinstance(raw_route, list) else []

    total_distance_ly: float | None = None
    previous_position = _star_position(_state(context, "Location").get("StarPos"))
    if route and previous_position is not None:
        accumulated_distance = 0.0
        for entry in route:
            position = _star_position(entry.get("StarPos"))
            if position is None:
                break
            accumulated_distance += math.dist(previous_position, position)
            previous_position = position
        else:
            total_distance_ly = round(accumulated_distance, 2)

    route_stars: list[dict[str, Any]] = []
    for hop, entry in enumerate(route, start=1):
        star_class = str(entry.get("StarClass") or "").strip().upper() or None
        raw_scoopable = entry.get("Scoopable")
        scoopable = raw_scoopable if isinstance(raw_scoopable, bool) else (
            star_class in FUEL_STAR_CLASSES if star_class else None
        )
        route_stars.append({
            "hop": hop,
            "system": _route_system(entry),
            "star_class": star_class,
            "fuel_star": scoopable,
        })

    non_fuel_stars = [star for star in route_stars if star["fuel_star"] is False]
    unknown_stars = [star for star in route_stars if star["fuel_star"] is None]
    arrival_star = route_stars[-1] if route_stars else None
    verified = bool(navigation["route_verified"] or navigation["target_reached"])

    if not verified:
        spoken_summary_fr = (
            f"Prochain système : {target_system}. Route non vérifiée ; ne saute pas encore."
        )
    elif navigation["target_reached"]:
        spoken_summary_fr = (
            f"Système atteint : {target_system}. Corps candidats : "
            f"{', '.join(target.get('targeted_fss_bodies') or []) or 'aucun'}."
        )
    else:
        distance_text = (
            f"{total_distance_ly:.2f} années-lumière"
            if total_distance_ly is not None
            else "distance totale indisponible"
        )
        jumps = len(route)
        jump_text = f"{jumps} saut" if jumps == 1 else f"{jumps} sauts"
        parts = [f"Prochain système : {target_system}. Distance totale : {distance_text}. {jump_text}."]
        if route_stars and not non_fuel_stars and not unknown_stars:
            parts.append("Que des Fuel Stars.")
        else:
            if non_fuel_stars:
                rendered = ", ".join(
                    f"saut {star['hop']} {star['system']}, classe {star['star_class'] or 'inconnue'}"
                    for star in non_fuel_stars
                )
                parts.append(f"Étoiles non-Fuel sur la route : {rendered}.")
            if unknown_stars:
                rendered = ", ".join(
                    f"saut {star['hop']} {star['system']}"
                    for star in unknown_stars
                )
                parts.append(f"Classe stellaire inconnue : {rendered}.")
        if arrival_star and arrival_star["fuel_star"] is not True:
            fuel_text = "non scoopable" if arrival_star["fuel_star"] is False else "scoopabilité inconnue"
            parts.append(
                f"À l’arrivée : étoile de classe {arrival_star['star_class'] or 'inconnue'}, {fuel_text}."
            )
        spoken_summary_fr = " ".join(parts)

    return {
        "verified": verified,
        "destination_system": target_system,
        "total_distance_ly": total_distance_ly,
        "jumps": len(route),
        "fuel_stars_only": bool(route_stars and not non_fuel_stars and not unknown_stars),
        "non_fuel_stars": non_fuel_stars,
        "unknown_stars": unknown_stars,
        "arrival_star": arrival_star,
        "spoken_summary_fr": spoken_summary_fr,
        "response_contract": "Read spoken_summary_fr verbatim. Add nothing else.",
    }


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
        "route_brief": _route_brief(target, context),
        "result": result_text,
    }


def _render_plan(plan: dict[str, Any]) -> str:
    plan["next_action"] = (
        "Call plotToTarget for navigation_instruction immediately. For Stratum sniping, plot the system first; "
        "after arrival select or FSS-resolve only targeted_fss_bodies. Never run a full-system FSS. "
        "Verify the final live NavRoute entry exactly matches the requested system before reporting a successful route. "
        "Any distance_ly in this result is measured from the planning source, not a live remaining distance. "
        "Close-star screening covers listed destinations only; never claim that Elite's intermediate hops were excluded."
    )
    return json.dumps(plan, ensure_ascii=False)


def _plan(parameters: PlannerParameters, context: dict[str, Any]) -> str:
    """Compatibility entry point for tests and callers without app config."""
    args = parameters.model_dump(exclude_none=True)
    return _render_plan(plan_exobiology(args, context))


def _expedition_queue(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one queue entry per system while preserving every candidate body."""
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
        queue.append({
            "system": system,
            "system_id64": system_target.get("system_id64"),
            "route_safety": system_target.get("route_safety"),
            "system_queue_position": system_index,
            "candidate_count": len(body_names),
            "targeted_fss_bodies": body_names,
            "candidate_bodies": [
                {
                    "body": str(body.get("body") or "").strip(),
                    "distance_to_arrival_ls": body.get("distance_to_arrival_ls"),
                    "atmosphere": body.get("atmosphere"),
                    "gravity_g": body.get("gravity_g"),
                    "surface_temperature_k": body.get("surface_temperature_k"),
                    "updated_at": body.get("updated_at"),
                }
                for body in bodies
                if str(body.get("body") or "").strip()
            ],
            "distance_ly": system_target.get("distance_ly"),
            "distance_from_planning_source_ly": system_target.get("distance_ly"),
            "distance_from_sol_ly": system_target.get("distance_from_sol_ly"),
            "estimated_jumps": system_target.get("estimated_jumps"),
            "route_order": system_target.get("route_order"),
            "confidence_tier": system_target.get("confidence_tier"),
            "confidence": system_target.get("confidence"),
            "instruction": (
                f"Dans {system}, vérifie uniquement ces {len(body_names)} corps candidats : {', '.join(body_names)}. "
                "Quand le système est terminé, operation next passe directement au système suivant."
            ),
        })
    return queue


def _migrate_expedition_to_system_queue(expedition: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Collapse legacy v2 body entries into v3 system entries."""
    if expedition.get("version") == 3 and expedition.get("queue_granularity") == "system":
        return expedition, False

    legacy_targets = expedition.get("targets") or []
    if not isinstance(legacy_targets, list):
        return expedition, False
    legacy_index = int(expedition.get("index", 0))
    if legacy_index >= len(legacy_targets):
        active_system = None
    else:
        active_system = str(_as_dict(legacy_targets[max(0, legacy_index)]).get("system") or "").strip()

    grouped: list[dict[str, Any]] = []
    by_system: dict[str, dict[str, Any]] = {}
    for raw_target in legacy_targets:
        target = _as_dict(raw_target)
        system = str(target.get("system") or "").strip()
        if not system:
            continue
        key = system.casefold()
        if key not in by_system:
            base = dict(target)
            base.pop("body", None)
            base.pop("body_queue_position", None)
            base.pop("body_count_in_system", None)
            base["system_queue_position"] = len(grouped) + 1
            base["targeted_fss_bodies"] = []
            base["candidate_bodies"] = []
            by_system[key] = base
            grouped.append(base)
        grouped_target = by_system[key]
        names = list(target.get("targeted_fss_bodies") or [])
        body_name = str(target.get("body") or "").strip()
        if body_name:
            names.append(body_name)
            grouped_target["candidate_bodies"].append({
                "body": body_name,
                "distance_to_arrival_ls": target.get("distance_to_arrival_ls"),
                "atmosphere": target.get("atmosphere"),
                "gravity_g": target.get("gravity_g"),
                "surface_temperature_k": target.get("surface_temperature_k"),
                "updated_at": target.get("updated_at"),
            })
        for name in names:
            clean_name = str(name or "").strip()
            if clean_name and clean_name not in grouped_target["targeted_fss_bodies"]:
                grouped_target["targeted_fss_bodies"].append(clean_name)

    for target in grouped:
        bodies = target["targeted_fss_bodies"]
        target["candidate_count"] = len(bodies)
        target["instruction"] = (
            f"Dans {target['system']}, vérifie uniquement ces {len(bodies)} corps candidats : {', '.join(bodies)}. "
            "Quand le système est terminé, operation next passe directement au système suivant."
        )

    migrated_index = len(grouped)
    if active_system:
        migrated_index = next(
            (index for index, target in enumerate(grouped) if _systems_match(target.get("system"), active_system)),
            len(grouped),
        )
    expedition["version"] = 3
    expedition["queue_granularity"] = "system"
    expedition["targets"] = grouped
    expedition["index"] = migrated_index
    expedition["system_count"] = len(grouped)
    return expedition, True


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
        self._last_announced_arrival: tuple[int, str] | None = None
        self._reported_candidate_scans: set[tuple[int, str]] = set()
        self._biological_signals: dict[tuple[int, str], int] = {}

    def _language(self) -> str:
        config = getattr(self._helper, "_config", {}) if self._helper else {}
        if not isinstance(config, dict):
            return "en"
        model_name = str(config.get("tts_model_name") or "").strip().casefold()
        if model_name.endswith(("-fr", "_fr")):
            return "fr"
        if model_name.endswith(("-en", "_en")):
            return "en"
        # The desktop launcher owns the shared speech-language selection and
        # deliberately persists it to STT. tts_language can remain at its old
        # default when a custom OpenAI-compatible TTS endpoint is selected.
        value = str(config.get("stt_language") or config.get("tts_language") or "en")
        return "fr" if value.casefold().startswith("fr") else "en"

    def _active_expedition_target(self) -> tuple[int, dict[str, Any]] | None:
        expedition = self._load_expedition()
        if not expedition:
            return None
        targets = expedition.get("targets")
        if not isinstance(targets, list):
            return None
        index = int(expedition.get("index", 0))
        if index < 0 or index >= len(targets) or not isinstance(targets[index], dict):
            return None
        return index, targets[index]

    def _speak(self, text: str, states: dict[str, Any]) -> None:
        if self._helper is not None:
            self._helper.speak_deterministic(text, states, context="exobiology_expedition")

    def _announce_expedition_arrival(
        self,
        index: int,
        target: dict[str, Any],
        states: dict[str, Any],
    ) -> None:
        system = str(target.get("system") or "").strip()
        arrival_key = (index, system.casefold())
        if not system or self._last_announced_arrival == arrival_key:
            return
        bodies = _candidate_bodies_in_visit_order(target)
        short_names = [_short_body_name(system, body) for body in bodies]
        language = self._language()
        rendered = _join_spoken(short_names, language)
        if language == "fr":
            text = (
                f"Destination d’expédition atteinte : {system}. "
                f"Au FSS, vérifie uniquement {rendered}. Je signalerai le First Footfall à chaque résolution."
            )
        else:
            text = (
                f"Expedition destination reached: {system}. "
                f"In FSS, check only {rendered}. I will report First Footfall as each body resolves."
            )
        self._last_announced_arrival = arrival_key
        self._speak(text, states)

    def _report_candidate_scan(
        self,
        index: int,
        target: dict[str, Any],
        content: dict[str, Any],
        states: dict[str, Any],
    ) -> None:
        body = str(content.get("BodyName") or "").strip()
        if "WasFootfalled" not in content or not body:
            return
        candidate_keys = {
            _body_key(name) for name in target.get("targeted_fss_bodies") or []
        }
        body_key = _body_key(body)
        if body_key not in candidate_keys:
            return
        report_key = (index, body_key)
        if report_key in self._reported_candidate_scans:
            return

        system = str(target.get("system") or "").strip()
        label = _short_body_name(system, body)
        bio_count = self._biological_signals.get(report_key, 0)
        footfalled = content.get("WasFootfalled") is True
        language = self._language()
        if language == "fr":
            if bio_count <= 0:
                text = f"{label} : aucun signal biologique, skip."
            elif footfalled:
                text = (
                    f"{label} : {bio_count} signal bio, First Footfall déjà pris. "
                    "Dépriorise ; DSS seulement si BioInsights confirme Stratum."
                )
            else:
                text = (
                    f"{label} : {bio_count} signal bio, aucun First Footfall enregistré. "
                    "DSS seulement si BioInsights confirme Stratum."
                )
        else:
            if bio_count <= 0:
                text = f"{label}: no biological signal; skip."
            elif footfalled:
                text = (
                    f"{label}: {bio_count} biological signal, First Footfall already claimed. "
                    "Deprioritize it; DSS only if BioInsights confirms Stratum."
                )
            else:
                text = (
                    f"{label}: {bio_count} biological signal, no First Footfall recorded. "
                    "DSS only if BioInsights confirms Stratum."
                )
        self._reported_candidate_scans.add(report_key)
        self._speak(text, states)

    def _expedition_event_sideeffect(self, event: Event, states: dict[str, Any]) -> None:
        if not isinstance(event, GameEvent):
            return
        active = self._active_expedition_target()
        if active is None:
            return
        index, target = active
        target_system = str(target.get("system") or "").strip()
        event_name = event.content.get("event")

        if event_name in {"FSDJump", "Location"}:
            current_system = str(
                event.content.get("StarSystem")
                or _state(states, "Location").get("StarSystem")
                or ""
            ).strip()
            if _systems_match(current_system, target_system):
                self._announce_expedition_arrival(index, target, states)
            elif event_name == "FSDJump":
                self._last_announced_arrival = None
            return

        event_system = str(
            event.content.get("StarSystem")
            or _state(states, "Location").get("StarSystem")
            or ""
        ).strip()
        if not _systems_match(event_system, target_system):
            return

        body = str(event.content.get("BodyName") or "").strip()
        report_key = (index, _body_key(body))
        candidate_keys = {
            _body_key(name) for name in target.get("targeted_fss_bodies") or []
        }
        if event_name == "FSSBodySignals" and report_key[1] in candidate_keys:
            self._biological_signals[report_key] = _biological_signal_count(event.content)
        elif event_name == "Scan":
            self._report_candidate_scan(index, target, event.content, states)

    def _configured_route_safety_policy(self) -> RouteSafetyPolicy | None:
        if self._helper is None:
            return None
        config = getattr(self._helper, "_config", None)
        if not isinstance(config, dict):
            return None
        return route_safety_policy_from_config(config)

    def _configured_plan(
        self,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        policy = self._configured_route_safety_policy()
        if policy is None:
            return plan_exobiology(args, context)
        return plan_exobiology(
            args,
            context,
            route_safety_policy=policy,
        )

    def _find_targets(
        self,
        parameters: PlannerParameters,
        context: dict[str, Any],
    ) -> str:
        return _render_plan(
            self._configured_plan(
                parameters.model_dump(exclude_none=True),
                context,
            )
        )

    def _load_expedition(self) -> dict[str, Any] | None:
        if self._expedition_file is None or not self._expedition_file.exists():
            return None
        try:
            expedition = json.loads(self._expedition_file.read_text(encoding="utf-8"))
            expedition, migrated = _migrate_expedition_to_system_queue(expedition)
            if migrated:
                self._save_expedition(expedition)
            return expedition
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
        # Expeditions navigate only between systems. Candidate bodies are a
        # read-only checklist and never become plot targets.
        plot_args = {"system": target["system"]}
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
            "route_brief": _route_brief(current or {}, states),
            "route_safety": current.get("route_safety") if current else None,
            "route_safety_coverage": expedition.get("route_safety"),
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
                "The queue is system-level. status reads; start replots without advancing; next/previous move exactly one system; "
                "set selects a one-based system index; reset only on explicit request. Set plot=false for queue-only changes."
            ),
        })]

    def _plan_tectonicas_expedition(self, parameters: TectonicasExpeditionParameters, context: dict[str, Any]) -> str:
        plan = self._configured_plan({
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
                "route_safety": plan.get("route_safety"),
            }, ensure_ascii=False)
        expedition = {
            "version": 3,
            "queue_granularity": "system",
            "strategy": "stratum_sniping",
            "source_system": plan.get("source_system"),
            "source_coords": plan.get("source_coords"),
            "jump_range": plan.get("jump_range"),
            "radius_ly": plan.get("radius_ly"),
            "max_arrival_ls": plan.get("max_arrival_ls"),
            "outward_staging_applied": plan.get("outward_staging_applied"),
            "route_safety": plan.get("route_safety"),
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
            "system_queue_size": len(queue),
            "current_target": queue[0],
            "targeted_fss_bodies": queue[0]["targeted_fss_bodies"],
            "route_safety": plan.get("route_safety"),
            "plot_result": plot_result,
            "route_brief": plot_result["route_brief"],
            "instruction": queue[0]["instruction"],
            "control": (
                "Say système suivant / expedition next after checking the listed candidates to advance exactly one system. "
                "Use operation=set with a one-based system index to select an explicit system."
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
            "route_brief": (
                plot_result["route_brief"] if plot_result is not None else _route_brief(target, context)
            ),
            "plot_result": plot_result,
        }, ensure_ascii=False)

    def on_chat_start(self, helper: PluginHelper):
        self._helper = helper
        self._expedition_file = Path(helper.get_plugin_data_path(self.plugin_manifest)) / "tectonicas-expedition.json"
        helper.register_sideeffect(self._expedition_event_sideeffect)
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
                method=self._find_targets,
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
                    "Immediately build and persist an efficient system-level queue from pre-Odyssey HMC Stratum leads when the commander asks Nova to "
                    "create a new managed expedition. Do not use it merely to inspect, resume, or change an existing "
                    "queue; use control_exobiology_expedition for that. Do not perform a guide lookup or web search first. Keep every exact candidate body in "
                    "one checklist per system, then plot the first system. At each system, select exposed bodies directly or resolve only the listed HMC "
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
                    "replots the current system; next/previous move exactly one whole system; set selects the supplied one-based system index; reset requires an explicit "
                    "reset request. Use plot=false for a queue-only set. Call next only for 'système suivant', 'expedition next', or explicit system completion/skip; "
                    "'guide me here', 'what now?', and current-body questions must not advance. The candidate bodies are a checklist, never separate queue entries. "
                    "After plotting, read route_brief.spoken_summary_fr verbatim and add nothing else. Never tell the commander to jump on an unverified route."
                ),
                parameters=ExpeditionControlParameters,
                method=self._control_expedition,
                action_type="ship",
                input_template=lambda args, _context: f"Exobiology expedition: {args.get('operation', 'status')}",
            )

    def on_chat_stop(self, helper: PluginHelper):
        pass
