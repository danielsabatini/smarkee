import json

from core_account_executor.http.health import Health, answer


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def body_of(response: bytes) -> tuple[int, dict[str, object]]:
    head, _, payload = response.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(payload)


def test_live_depends_only_on_the_heartbeat() -> None:
    clock = Clock()
    health = Health(stale_after_seconds=10, monotonic=clock)
    health.add_check("nats", lambda: False)  # dependência fora não derruba a liveness
    assert body_of(answer(health, "GET", "/health/live"))[0] == 200
    clock.now = 11
    assert body_of(answer(health, "GET", "/health/live"))[0] == 503
    health.beat()
    assert body_of(answer(health, "GET", "/health/live"))[0] == 200


def test_ready_requires_startup_and_every_check() -> None:
    health = Health()
    state = {"nats": True}
    health.add_check("nats", lambda: state["nats"])
    assert body_of(answer(health, "GET", "/health/ready"))[0] == 503
    health.mark_started()
    assert body_of(answer(health, "GET", "/health/ready"))[0] == 200
    state["nats"] = False
    status, body = body_of(answer(health, "GET", "/health/ready"))
    assert status == 503 and body["checks"] == {"nats": "DOWN"}


def test_startup_reports_starting_until_marked() -> None:
    health = Health()
    assert body_of(answer(health, "GET", "/health/startup")) == (503, {"status": "STARTING"})
    health.mark_started()
    assert body_of(answer(health, "GET", "/health/startup")) == (200, {"status": "UP"})


def test_unknown_routes_and_methods_are_refused() -> None:
    health = Health()
    assert body_of(answer(health, "GET", "/config"))[0] == 404
    assert body_of(answer(health, "POST", "/health/live"))[0] == 405
