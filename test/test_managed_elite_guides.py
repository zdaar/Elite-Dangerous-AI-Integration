import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE_ROOT = ROOT / "guides" / "elite"


def test_elite_guide_bundle_contains_runtime_authorities() -> None:
    required = {
        "elite-exobiology/SKILL.md",
        "elite-exobiology/references/field-guide.md",
        "elite-exobiology/references/species-values.md",
        "elite-exobiology/references/targeting.md",
        "elite-hcs-astra/SKILL.md",
        "elite-hcs-astra/references/commands.md",
        "elite-spansh/SKILL.md",
        "elite-spansh/references/search-api.md",
        "elite-station-services/SKILL.md",
    }

    bundled = {
        path.relative_to(GUIDE_ROOT).as_posix()
        for path in GUIDE_ROOT.rglob("*.md")
    }
    assert required <= bundled
    assert len(bundled) >= 18


def test_electron_builder_packages_elite_guide_as_managed_resource() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    resources = package["build"]["extraResources"]

    guide_resource = next(
        resource for resource in resources
        if resource.get("from") == "guides/elite"
    )
    assert guide_resource["to"] == "managed-guides/elite"
    assert guide_resource["filter"] == ["**/*.md"]


def test_managed_plugins_deploy_to_the_backend_working_directory() -> None:
    electron_source = (ROOT / "electron" / "index.js").read_text(encoding="utf-8")

    assert "path.join(config.backend_cwd, 'plugins')" in electron_source
    assert "path.join(config.backend_cwd, 'managed-plugins.json')" in electron_source
