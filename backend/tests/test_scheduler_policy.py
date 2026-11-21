import pytest

from hunter.scheduler import ScanOutcome, ScanPolicy, SourceClass, source_class


@pytest.mark.parametrize(("priority", "tier", "minutes"), [
    (91, SourceClass.HOT_NEWS, 10),
    (90, SourceClass.HOT_NEWS, 10),
    (89, SourceClass.TRENDING, 30),
    (70, SourceClass.TRENDING, 30),
    (69, SourceClass.PRIORITY_CREATOR, 60),
    (50, SourceClass.PRIORITY_CREATOR, 60),
    (49, SourceClass.NORMAL, 180),
    (20, SourceClass.NORMAL, 180),
    (19, SourceClass.LOW_ACTIVITY, 720),
    (0, SourceClass.LOW_ACTIVITY, 720),
])
def test_source_classes_and_dashboard_overrides(priority: int, tier: SourceClass, minutes: int) -> None:
    policy = ScanPolicy()
    assert source_class(priority) == tier
    assert policy.base_seconds(priority, {}) == minutes * 60
    assert policy.base_seconds(priority, {tier.value: 5}) == 300


@pytest.mark.parametrize(("outcomes", "factor"), [
    ([], 1.0),
    ([ScanOutcome.STRONG], 0.5),
    ([ScanOutcome.EMPTY], 1.5),
    ([ScanOutcome.EMPTY, ScanOutcome.STRONG], 0.75),
    ([ScanOutcome.STRONG, ScanOutcome.EMPTY], 0.75),
    ([ScanOutcome.NORMAL, ScanOutcome.EMPTY], 1.0),
    ([ScanOutcome.EMPTY] * 12, 4.0),
    ([ScanOutcome.STRONG, *([ScanOutcome.EMPTY] * 12)], 2.0),
    ([ScanOutcome.STRONG] * 12, 0.5),
])
def test_adaptation_newest_scan_first(outcomes: list[ScanOutcome], factor: float) -> None:
    assert ScanPolicy().delay_seconds(600, outcomes) == pytest.approx(600 * factor)


def test_exponential_backoff_and_jitter_bounds() -> None:
    policy = ScanPolicy()
    assert policy.delay_seconds(600, failures=1) == 1200
    assert policy.delay_seconds(600, failures=2) == 2400
    assert policy.delay_seconds(600, failures=9999) == 9600
    assert policy.delay_seconds(600, failures=1, jitter=0.0) == 1080
    assert policy.delay_seconds(600, failures=1, jitter=1.0) == pytest.approx(1320)
    assert policy.delay_seconds(600, [ScanOutcome.STRONG], jitter=0.0) == 300
    assert policy.delay_seconds(600, [ScanOutcome.STRONG], jitter=1.0) == pytest.approx(330)
    assert policy.delay_seconds(600, [ScanOutcome.EMPTY] * 6, jitter=1.0) == 2400
    with pytest.raises(ValueError, match="between 0 and 1"):
        policy.delay_seconds(600, jitter=1.1)
