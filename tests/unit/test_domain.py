from windowkeeper.domain.models import RawWindow
from windowkeeper.domain.scheduling import decide_schedule, deterministic_jitter
from windowkeeper.domain.status import overall_state
from windowkeeper.domain.usage import clamped_percent, freshness, normalize_usage


def test_usage_normalization_uses_duration_semantics() -> None:
    usage = normalize_usage(
        {
            "rateLimitsByLimitId": {
                "codex": {
                    "windows": [
                        {
                            "name": "week",
                            "usedPercent": 33,
                            "windowDurationMins": 10_080,
                            "resetsAt": 200,
                        },
                        {
                            "name": "short",
                            "usedPercent": 140,
                            "windowDurationMins": 300,
                            "resetsAt": 100,
                        },
                    ]
                }
            }
        }
    )
    assert usage.short and usage.short.slot == "short"
    assert usage.weekly and usage.weekly.slot == "week"
    assert clamped_percent(140) == 100


def test_schedule_is_deterministic_and_deduplicated() -> None:
    short = RawWindow("short", 10, 300, 2_000)
    first = decide_schedule(
        account_id="a",
        enabled=True,
        auth_verified=True,
        short=short,
        now_ms=1_000_000,
        safety_delay_seconds=60,
        jitter_max_seconds=30,
    )
    second = decide_schedule(
        account_id="a",
        enabled=True,
        auth_verified=True,
        short=short,
        now_ms=1_000_000,
        safety_delay_seconds=60,
        jitter_max_seconds=30,
    )
    assert first == second
    assert first.window_key == "reported:2000"
    assert deterministic_jitter("a", first.window_key, 30) <= 30
    duplicate = decide_schedule(
        account_id="a",
        enabled=True,
        auth_verified=True,
        short=short,
        now_ms=1_000_000,
        safety_delay_seconds=60,
        jitter_max_seconds=30,
        existing_window_keys={first.window_key},
    )
    assert duplicate.run_at_ms is None


def test_freshness_and_status_are_conservative() -> None:
    assert freshness(None, 1_000) == "UNKNOWN"
    assert freshness(1_000, 1_000 + 31 * 60_000) == "STALE"
    assert (
        overall_state(
            enabled=True,
            auth_state="AUTH_REQUIRED",
            worker_state="STOPPED",
            usage_state="FRESH",
            activation_state="UNSCHEDULED",
        )
        == "ACTION_REQUIRED"
    )
