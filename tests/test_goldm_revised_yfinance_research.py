from datetime import datetime, timedelta, timezone

import pytest

from goldm_revised.yfinance_research import YAHOO_PROXY_WARNING, chunk_ranges


def test_yahoo_intraday_ranges_are_end_exclusive_and_bounded() -> None:
    start = datetime(2026, 8, 2, tzinfo=timezone.utc)
    end = datetime(2026, 8, 19, tzinfo=timezone.utc)

    ranges = list(chunk_ranges(start, end))

    assert ranges[0][0] == start
    assert ranges[-1][1] == end
    assert all(right - left <= timedelta(days=7) for left, right in ranges)
    assert all(current[1] == following[0] for current, following in zip(ranges, ranges[1:]))


def test_yahoo_chunk_rejects_more_than_seven_days() -> None:
    with pytest.raises(ValueError, match="between 1 and 7"):
        list(chunk_ranges(datetime(2026, 8, 1), datetime(2026, 8, 2), days=8))


def test_proxy_warning_keeps_gc_f_separate_from_broker_symbol() -> None:
    assert "not broker GOLD.i#" in YAHOO_PROXY_WARNING
