import time, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from workbench.policy import (
    Window,
    Availability,
    UsagePolicy,
    PREFERENCE,
    validate_config,
    Blocked,
)
from workbench.common import ContractError


@pytest.mark.parametrize(
    "remaining,expected",
    [
        (0, False),
        (5, False),
        (5.1, False),
        (9, False),
        (9.999, False),
        (10, True),
        (35, True),
        (100, True),
        (101, False),
        (-1, False),
        (float("nan"), False),
    ],
)
def test_threshold(remaining, expected):
    assert Window("daily", remaining).eligible() == expected


@pytest.mark.parametrize(
    "remaining,task,expected",
    [(35, 31, False), (35, 20, True), (10, 4, False), (10, 3, True)],
)
def test_budget(remaining, task, expected):
    assert Window("daily", remaining, task=task).eligible() == expected


def obs(route, n):
    return Availability(route, True, True, False, time.time(), [Window("day", n)])


def test_multiple_windows():
    x = obs("worker.opus", 70)
    x.windows.append(Window("week", 0))
    assert not x.eligible()


def test_stale_unknown():
    x = obs("worker.opus", 50)
    x.observed -= 86401
    assert not x.eligible()
    x.observed = time.time()
    x.allowance_known = False
    assert not x.eligible()


def test_promote_best():
    xs = {r: obs(r, n) for r, n in zip(PREFERENCE, [4, 40, 70])}
    assert UsagePolicy.choose(xs, "worker.extra") == "worker.astra"
    xs["worker.opus"] = obs("worker.opus", 30)
    assert UsagePolicy.choose(xs, "worker.extra") == "worker.opus"
    xs["worker.opus"] = obs("worker.opus", 7)
    assert UsagePolicy.choose(xs, "worker.astra") == "worker.astra"


def test_unknown_keep_current():
    x = Availability("worker.astra")
    assert UsagePolicy.choose({"worker.astra": x}, "worker.astra") == "worker.astra"
    assert UsagePolicy.choose({"worker.astra": x}) is None
    x.blocked = "quota"
    assert UsagePolicy.choose({"worker.astra": x}, "worker.astra") is None


def test_poll_once_under_concurrency(store):
    p = UsagePolicy(store)
    with ThreadPoolExecutor(10) as ex:
        assert sum(ex.map(lambda _: p.claim_poll("account", 100000), range(10))) == 1
    assert not p.claim_poll("account", 99999)
    assert not p.claim_poll("account", 186399)
    assert p.claim_poll("account", 186400)


def test_poll_persisted_failure(store):
    assert UsagePolicy(store).claim_poll("a", 100000)
    assert not UsagePolicy(store).claim_poll("a", 100001)


def test_config():
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    validate_config(cfg)
    cfg["paid_overage"] = True
    with pytest.raises(ContractError):
        validate_config(cfg)


def test_distinct_roles():
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    cfg["routes"]["worker.extra"]["conversation_url"] = "https://chatgpt.com/c/one"
    cfg["routes"]["adviser.extra"]["conversation_url"] = "https://chatgpt.com/c/one"
    with pytest.raises(ContractError):
        validate_config(cfg)


def test_shared_pool_reservations(store):
    p = UsagePolicy(store)
    w = [Window("weekly", 30, task=12)]
    p.reserve("shared", "one", w)
    with pytest.raises(Blocked):
        p.reserve("shared", "two", w)
    p.reserve("shared", "one", w)  # renewing own reservation must not double count
    p.release("one")
    p.reserve("shared", "two", w)


def test_current_worker_reserve_and_unknown_policy():
    x = obs("worker.opus", 5)
    assert UsagePolicy.choose({"worker.opus": x}, "worker.opus") is None
    x = obs("worker.opus", 7)
    assert UsagePolicy.choose({"worker.opus": x}, "worker.opus") == "worker.opus"
    x.windows[0].task = 20
    assert UsagePolicy.choose({"worker.opus": x}, "worker.opus") is None
    unknown = Availability("worker.opus")
    assert (
        UsagePolicy.choose(
            {"worker.opus": unknown, "worker.astra": obs("worker.astra", 70)},
            "worker.opus",
        )
        == "worker.opus"
    )
