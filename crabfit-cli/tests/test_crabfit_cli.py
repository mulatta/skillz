# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Regression tests for Crab.fit time slot handling."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crabfit_cli


def _assert_equal[T](actual: T, expected: T) -> None:
    if actual != expected:
        msg = f"{actual!r} != {expected!r}"
        raise AssertionError(msg)


class TimeSlotTests(unittest.TestCase):
    """Test Crab.fit slot formats used by public and weekday-only events."""

    def test_expand_hourly_slots_to_quarters(self) -> None:
        """Event hour slots are expanded to UI availability granularity."""
        _assert_equal(
            crabfit_cli.expand_time_slots(["0000-3", "0100-3"]),
            [
                "0000-3",
                "0015-3",
                "0030-3",
                "0045-3",
                "0100-3",
                "0115-3",
                "0130-3",
                "0145-3",
            ],
        )

    def test_parse_specific_date_slot(self) -> None:
        """Specific-date slots are parsed from UTC into the display timezone."""
        _assert_equal(
            crabfit_cli.parse_time_slot("0000-05052026", "Asia/Seoul"),
            dt.datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )

    def test_parse_weekday_slot(self) -> None:
        """Weekday-only slots use Crab.fit's current-week anchoring."""
        reference = dt.datetime(2026, 5, 4, 12, tzinfo=dt.UTC)
        _assert_equal(
            crabfit_cli.parse_time_slot("0000-3", "Asia/Seoul", today=reference),
            dt.datetime(2026, 5, 6, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )

    def test_group_consecutive_slots_uses_quarter_hour_steps(self) -> None:
        """Consecutive availability groups are based on 15-minute slots."""
        _assert_equal(
            crabfit_cli.group_consecutive_slots(
                ["0000-3", "0015-3", "0030-3", "0100-3"],
                "Asia/Seoul",
            ),
            [["0000-3", "0015-3", "0030-3"], ["0100-3"]],
        )

    def test_availability_map_uses_expanded_event_slots(self) -> None:
        """Quarter-hour participant availability is counted for hourly events."""
        event_times = crabfit_cli.expand_time_slots(["0000-3"])
        people = [
            {"name": "Alice", "availability": ["0000-3", "0015-3"]},
            {"name": "Bob", "availability": ["0015-3", "0030-3"]},
        ]
        _assert_equal(
            crabfit_cli.build_availability_map(event_times, people),
            {
                "0000-3": ["Alice"],
                "0015-3": ["Alice", "Bob"],
                "0030-3": ["Bob"],
                "0045-3": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
