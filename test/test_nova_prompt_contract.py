from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nova_profile_allows_explicit_tone_overrides() -> None:
    profile = (ROOT / "profiles" / "nova-operational-fr.txt").read_text(encoding="utf-8")

    assert "autorise immédiatement ce ton" in profile
    assert "Ne jamais la refuser au nom du mode opérationnel" in profile
    assert "ne signifie jamais `next`" in profile
    assert "Raconte-moi une blague » : raconter une blague, sans outil ni refus" in profile


def test_nova_profile_prioritizes_direct_tools_and_live_state() -> None:
    profile = (ROOT / "profiles" / "nova-operational-fr.txt").read_text(encoding="utf-8")

    assert "Action directe, statut live ou outil nommé : appeler immédiatement" in profile
    assert "ni guide, ni recherche web, ni recherche mémoire avant" in profile
    assert "La mémoire ne sert que de contexte historique" in profile


def test_nova_profile_separates_route_queue_and_distance_semantics() -> None:
    profile = (ROOT / "profiles" / "nova-operational-fr.txt").read_text(encoding="utf-8")

    assert "`NavInfo.NavRoute[0]` est le prochain saut" in profile
    assert "`NavInfo.NavRoute[-1]` est la destination finale" in profile
    assert "distance depuis la source de planification" in profile
    assert "`set` sélectionne un index 1-based" in profile
    assert "Mismatch : demandé X, route vers Y" in profile
    assert "lire `NavInfo.NavRoute`, sans consulter l’expédition ni la mémoire" in profile


def test_nova_profile_blocks_full_fss_and_false_first_logged_claims() -> None:
    profile = (ROOT / "profiles" / "nova-operational-fr.txt").read_text(encoding="utf-8")

    assert "Ne jamais demander un FSS complet" in profile
    assert "ne prouve ni First Footfall, ni First Logged" in profile
    assert "potentiel First Logged" in profile
    assert "avant un événement de vente qui le confirme" in profile


def test_exobiology_action_prompts_keep_direct_tool_scope() -> None:
    actions = (ROOT / "src" / "lib" / "actions" / "actions_web.py").read_text(encoding="utf-8")
    plugin = (ROOT / "plugins" / "exobiology-profit-planner" / "plugin.py").read_text(encoding="utf-8")

    assert "Do not call web_search_agent, body_finder, or a guide lookup first or as a fallback" in actions
    assert "current route/queue status" in actions
    assert "set selects the supplied one-based index" in plugin
    assert "'guide me here', 'what now?', and current-body questions must not advance" in plugin
    assert '"distance_from_planning_source_ly"' in plugin
    assert '"route_destination"' in plugin
