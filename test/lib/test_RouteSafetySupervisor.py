from src.lib.RouteSafety import SystemSafetyAssessment
from src.lib.RouteSafetySupervisor import RouteHop, RouteSafetySupervisor


def hop(name: str, address: int, x: float) -> RouteHop:
    return RouteHop(name, address, (x, 0.0, 0.0))


def assessment(name: str, address: int, status: str) -> SystemSafetyAssessment:
    return SystemSafetyAssessment(name, address, status, "test", {})  # type: ignore[arg-type]


def lookup(statuses: dict[int, str]):
    return lambda address: (
        assessment(str(address), address, statuses[address])
        if address in statuses else None
    )


def test_safe_route_and_unknown_route_are_distinguished() -> None:
    route = [hop("Start", 1, 0), hop("A", 2, 10), hop("Destination", 3, 20)]

    safe = RouteSafetySupervisor().inspect_route(route, lookup({2: "safe", 3: "safe"}))
    unknown = RouteSafetySupervisor().inspect_route(route, lookup({2: "safe", 3: "unknown"}))

    assert safe.action == "route_safe"
    assert unknown.action == "route_accepted_unknown"
    assert unknown.unknown_hops == 1


def test_unsafe_route_shortens_to_last_safe_then_bypasses_and_replots() -> None:
    supervisor = RouteSafetySupervisor()
    start = hop("Start", 1, 0)
    safe_a = hop("Safe A", 2, 10)
    dangerous = hop("Danger", 3, 20)
    destination = hop("Destination", 4, 30)

    unsafe = supervisor.inspect_route(
        [start, safe_a, dangerous, destination],
        lookup({2: "safe", 3: "dangerous", 4: "safe"}),
    )
    boundary_route = supervisor.inspect_route(
        [start, safe_a],
        lookup({2: "safe"}),
    )
    at_boundary = supervisor.on_jump(safe_a)
    bypass = hop("Bypass", 5, 18)
    selected = supervisor.set_bypass(bypass)
    bypass_route = supervisor.inspect_route(
        [safe_a, bypass],
        lookup({5: "safe"}),
    )
    at_bypass = supervisor.on_jump(bypass)
    safe_replot = supervisor.inspect_route(
        [bypass, destination],
        lookup({4: "safe"}),
    )

    assert unsafe.action == "plot_boundary"
    assert unsafe.target == safe_a
    assert unsafe.dangerous == dangerous
    assert unsafe.hop_number == 2
    assert boundary_route.action == "none"
    assert at_boundary.action == "find_bypass"
    assert selected.target == bypass
    assert bypass_route.action == "none"
    assert at_bypass.action == "plot_original"
    assert at_bypass.target == destination
    assert safe_replot.action == "route_safe"
    assert supervisor.phase == "safe"


def test_immediate_danger_requests_bypass_without_plotting_current_system() -> None:
    supervisor = RouteSafetySupervisor()
    decision = supervisor.inspect_route(
        [hop("Current", 1, 0), hop("Danger", 2, 10), hop("Destination", 3, 20)],
        lookup({2: "dangerous", 3: "safe"}),
    )

    assert decision.action == "find_bypass"
    assert decision.target.name == "Current"


def test_repeated_unsafe_replots_track_forbidden_systems_and_stop_loop() -> None:
    supervisor = RouteSafetySupervisor(max_bypass_attempts=2)
    start = hop("Start", 1, 0)
    first_danger = hop("Danger 1", 2, 10)
    second_danger = hop("Danger 2", 3, 12)
    destination = hop("Destination", 4, 30)

    first = supervisor.inspect_route(
        [start, first_danger, destination],
        lookup({2: "dangerous", 4: "safe"}),
    )
    supervisor.set_bypass(hop("Bypass 1", 5, 8))
    supervisor.on_jump(hop("Bypass 1", 5, 8))
    second = supervisor.inspect_route(
        [hop("Bypass 1", 5, 8), second_danger, destination],
        lookup({3: "dangerous", 4: "safe"}),
    )
    supervisor.set_bypass(hop("Bypass 2", 6, 9))
    supervisor.on_jump(hop("Bypass 2", 6, 9))
    stopped = supervisor.inspect_route(
        [hop("Bypass 2", 6, 9), first_danger, destination],
        lookup({2: "dangerous", 4: "safe"}),
    )

    assert first.action == "find_bypass"
    assert second.action == "find_bypass"
    assert supervisor.forbidden_system_ids == {2, 3}
    assert stopped.action == "manual_bypass_required"
    assert supervisor.phase == "manual_required"
