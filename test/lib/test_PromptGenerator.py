from src.lib.PromptGenerator import PromptGenerator


class EmptySystemDatabase:
    def get_system_info(self, _system_name: str, async_fetch: bool = False):
        assert async_fetch is True
        return None


def test_nav_route_jump_count_equals_remaining_route_entries() -> None:
    """NavInfo excludes the current system, so no extra subtraction is valid."""
    generator = PromptGenerator.__new__(PromptGenerator)
    generator.system_db = EmptySystemDatabase()
    generator.registered_status_generators = []
    generator.generate_vehicle_status = lambda _status, _combat: ("Ship", {})
    generator._get_active_quest_entries = lambda: []

    status = generator.generate_status_message({
        "NavInfo": {
            "NavRoute": [
                {"StarSystem": "Next Hop"},
                {"StarSystem": "Second Hop"},
                {"StarSystem": "Destination"},
            ],
        },
    })

    assert "# Nav Route" in status
    assert "Jumps: 3" in status
    assert "Jumps: 2" not in status
