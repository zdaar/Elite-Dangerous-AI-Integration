import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field

from lib.PluginBase import PluginBase, PluginManifest
from lib.PluginHelper import PluginHelper


ROUTE_URL = "https://spansh.co.uk/api/exobiology/route"
RESULT_URL = "https://spansh.co.uk/api/results/{job_id}"
HEADERS = {"User-Agent": "COVAS-NEXT/exobiology-profit-planner"}


class PlannerParameters(BaseModel):
    strategy: Literal["auto", "throughput"] = "auto"
    radius: int = Field(default=50, ge=25, le=5000)
    max_results: int = Field(default=8, ge=1, le=20)


class FieldGuideParameters(BaseModel):
    genuses: list[str] = Field(description="Biological genera shown by the Detailed Surface Scanner filters")


class GuideLookupParameters(BaseModel):
    query: str = Field(min_length=3, description="The exact Elite Dangerous mechanics question to verify")
    max_chunks: int = Field(default=5, ge=1, le=8)


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
}


FIELD_GUIDE = {
    "stratum": {"priority": 1, "terrain": "flat, open plains; avoid broken ground", "appearance": "broad layered mats or low plate-like colonies", "method": "Use the DSS Stratum filter; fly low over the brightest solid-colour patches, land with long clear sight-lines."},
    "clypeus": {"priority": 2, "terrain": "rocky slopes and rough highlands, not flat plains", "appearance": "large upright fan/shell structures", "method": "Use the Clypeus filter; search illuminated rocky slopes from the ship or SRV."},
    "tussock": {"priority": 5, "terrain": "open plains and gentle slopes", "appearance": "small grass-like clumps", "method": "Use the Tussock filter; low-altitude visual search or SRV because individual clumps are small."},
    "frutexa": {"priority": 4, "terrain": "rocky ground, slopes and foothills", "appearance": "bushy branching shrubs", "method": "Use the Frutexa filter; scan rough foothills rather than smooth plains."},
    "osseus": {"priority": 3, "terrain": "rocky and mountainous ground", "appearance": "pale branching bone/coral-like growths", "method": "Use the Osseus filter; search rock fields and mountain bases."},
    "fungoida": {"priority": 6, "terrain": "mountainous, rocky terrain and crater slopes", "appearance": "mushroom-like caps or stalked colonies", "method": "Use the Fungoida filter; search rugged slopes, accepting slower travel only after higher-value genera."},
    "cactoida": {"priority": 7, "terrain": "rocky plains and slopes", "appearance": "upright cactus-like columns or clusters", "method": "Use the Cactoida filter and fly low across moderately rough ground."},
    "bacterium": {"priority": 8, "terrain": "flat ground matching its colour; often low contrast", "appearance": "thin discoloured surface patches", "method": "Lowest priority here. Use the DSS Bacterium filter, then camera/NV contrast and low-angle light; skip if search time damages credits/hour."},
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


def _location(context: dict[str, Any]) -> str:
    location = _state(context, "Location")
    system = str(location.get("StarSystem") or location.get("star_system") or "").strip()
    if not system or system.casefold() == "unknown":
        raise ValueError("Current system is unknown; wait for a Location or FSDJump event.")
    return system


def _jump_range(context: dict[str, Any]) -> float:
    ship = _state(context, "ShipInfo")
    loadout = _state(context, "Loadout")
    for value in (
        ship.get("CurrentJumpRange"), ship.get("MaximumJumpRange"),
        ship.get("ReportedMaximumJumpRange"), loadout.get("MaxJumpRange"),
    ):
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 2)
    return 35.0


def _poll(job_id: str) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        response = requests.get(RESULT_URL.format(job_id=job_id), headers=HEADERS, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("state") == "failed":
            raise RuntimeError(payload.get("error") or "Spansh route failed")
        if payload.get("state") == "completed" or payload.get("result"):
            return payload.get("result") or []
        time.sleep(0.5)
    raise TimeoutError("Spansh route did not finish within 25 seconds")


def _jumps(source: dict[str, Any], target: dict[str, Any], jump_range: float) -> int:
    delta = [float(target.get(a) or 0) - float(source.get(a) or 0) for a in ("x", "y", "z")]
    return max(1, math.ceil(math.sqrt(sum(v * v for v in delta)) / max(jump_range, 1) * 1.1))


def _plan(parameters: PlannerParameters, context: dict[str, Any]) -> str:
    source_system = _location(context)
    jump_range = _jump_range(context)
    response = requests.post(
        ROUTE_URL,
        data={
            "from": source_system,
            "range": str(jump_range),
            "radius": str(parameters.radius),
            "max_results": str(parameters.max_results),
            "min_value": "16000000",
            "loop": "0",
        },
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    job_id = response.json().get("job")
    if not job_id:
        raise RuntimeError("Spansh did not return a route job id")

    result = _poll(job_id)
    targets: list[dict[str, Any]] = []
    if result:
        source = result[0]
        for system in result[1:]:
            jumps = _jumps(source, system, jump_range)
            for body in system.get("bodies") or []:
                organisms = [
                    {"species": item.get("subtype") or item.get("type"), "value": int(item.get("value") or 0)}
                    for item in body.get("landmarks") or []
                    if item.get("subtype") or item.get("type")
                ]
                priority_value = sum(item["value"] for item in organisms)
                total_value = int(body.get("landmark_value") or priority_value)
                arrival = float(body.get("distance_to_arrival") or 0)
                seconds = max(60, round(jumps * 50 + 35 + 0.75 * math.sqrt(arrival) + 150 + max(1, len(organisms)) * 180))
                targets.append({
                    "system": system.get("name"), "body": body.get("name"),
                    "estimated_jumps": jumps, "distance_to_arrival_ls": round(arrival, 1),
                    "confirmed_total_value": total_value, "priority_species": organisms,
                    "estimated_credits_per_hour": round((priority_value or total_value) / seconds * 3600),
                })
    targets.sort(key=lambda x: (-x["estimated_credits_per_hour"], -x["confirmed_total_value"]))
    targets = targets[:parameters.max_results]
    best = targets[0] if targets else None
    return json.dumps({
        "strategy": "confirmed_throughput",
        "source_system": source_system,
        "jump_range": jump_range,
        "targets": targets,
        "recommended_target": best,
        "navigation_instruction": {"system": best["system"], "body": best["body"]} if best else None,
        "next_action": "Immediately call plotToTarget for navigation_instruction.system; do not ask for confirmation.",
        "operational_notes": [
            "Complete all three samples before starting another species.",
            "Prioritize listed high-value organisms and skip low-value detours.",
            "Unsold biodata is lost on death.",
        ],
    }, ensure_ascii=False)


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
    candidates = [
        Path(configured) if configured else None,
        Path.home() / "COVAS-Elite-Guide",
        Path(os.environ.get("USERPROFILE", "")) / "Claude" / "Projects" / "Elite Dangerous" / ".claude" / "skills",
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
            "If evidence is insufficient, say 'Guide local insuffisant' and perform one sourced search."
        ),
    }, ensure_ascii=False)


class ExobiologyProfitPlannerPlugin(PluginBase):
    def __init__(self, plugin_manifest: PluginManifest):
        super().__init__(plugin_manifest)

    def on_chat_start(self, helper: PluginHelper):
        helper.register_status_generator(lambda _states: [("Authoritative Elite facts policy", {
            "rule": "For every Elite Dangerous gameplay or system fact, call lookup_elite_guide before answering.",
            "forbidden_sources": ["model training knowledge", "conversation memory", "prior assistant claims", "inference"],
            "allowed_sources": ["lookup_elite_guide evidence", "an explicit sourced search when local evidence is insufficient"],
            "failure_response": "Information non vérifiée.",
            "style": "zero roleplay; concise operational fact only",
        })])
        if "find_exobiology_targets" not in helper._action_manager.actions:
            helper.register_action(
                name="find_exobiology_targets",
                description=(
                    "Find and rank a NEW destination planet near the commander's live system for maximum exobiology credits per hour. "
                    "Use only when asked to find, replace, or optimize a destination. Never use while the commander is asking how to "
                    "locate or sample organisms on the current planet. After receiving a result, call plotToTarget with the "
                    "recommended navigation system without asking for confirmation. Do not perform preliminary web searches or status checks."
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
                    "Do not search for another planet and do not invent exact coordinates."
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
                    "MANDATORY source-of-truth lookup for every factual Elite Dangerous mechanics, system, control, equipment, economy, "
                    "navigation, exploration, combat, engineering, or exobiology question. Call this before answering even when the answer "
                    "seems obvious or appeared earlier in conversation. The model's training knowledge and conversational memory are never "
                    "valid sources for game facts. Relay only returned evidence; if insufficient, use one explicitly sourced web search."
                ),
                parameters=GuideLookupParameters,
                method=_guide_lookup,
                action_type="web",
                input_template=lambda args, _context: f"Consulting the verified Elite guide: {args.get('query', '')}",
            )

    def on_chat_stop(self, helper: PluginHelper):
        pass
