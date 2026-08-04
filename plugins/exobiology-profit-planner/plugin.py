import json
import math
import time
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


class ExobiologyProfitPlannerPlugin(PluginBase):
    def __init__(self, plugin_manifest: PluginManifest):
        super().__init__(plugin_manifest)

    def on_chat_start(self, helper: PluginHelper):
        if "find_exobiology_targets" in helper._action_manager.actions:
            return
        helper.register_action(
            name="find_exobiology_targets",
            description=(
                "Find and rank currently known exobiology targets near the commander's live system for maximum credits per hour. "
                "Use immediately for exobiology money-making requests. After receiving a result, call plotToTarget with the "
                "recommended navigation system without asking for confirmation. Do not perform preliminary web searches or status checks."
            ),
            parameters=PlannerParameters,
            method=_plan,
            action_type="web",
            input_template=lambda args, _context: "Optimizing an exobiology route from the current system",
        )

    def on_chat_stop(self, helper: PluginHelper):
        pass
