from datetime import UTC, datetime, timedelta

from shadow_fleet.quality import assess_observations

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def point(seconds, *, conflict=False, skew=False):
    return {'provider_time':NOW + timedelta(seconds=seconds), 'time_conflict':conflict, 'clock_skew':skew}


def test_quality_reports_only_observed_intervals_at_or_above_threshold():
    report = assess_observations([point(0), point(899, conflict=True), point(1799, skew=True)], truncated=False)
    assert report.interval_status == 'assessed'
    assert report.long_interval_count == 1
    assert report.long_intervals[0].before == NOW + timedelta(seconds=899)
    assert report.long_intervals[0].duration_seconds == 900
    assert report.conflict_count == 1 and report.clock_skew_count == 1


def test_quality_distinguishes_truncation_and_insufficient_observations():
    for points, truncated, wanted in [([point(0), point(900)], True, 'truncated'),
                                       ([point(0)], False, 'insufficient')]:
        report = assess_observations(points, truncated=truncated)
        assert report.interval_status == wanted
        assert report.long_interval_count is None and report.long_intervals == []


def test_long_interval_details_are_capped_without_hiding_total():
    report = assess_observations([point(i * 1000) for i in range(16)], truncated=False)
    assert report.long_interval_count == 15 and len(report.long_intervals) == 10
