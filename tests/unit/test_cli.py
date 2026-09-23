from __future__ import annotations

import argparse

import pytest

from qual_event_engine.cli import (
    _validate_session_id,
    _validate_strategy_id,
    _validate_utc_timestamp,
)


def test_cli_validate_utc_timestamp_valid() -> None:
    valid_ts = "2026-09-21T10:30:00Z"
    result = _validate_utc_timestamp(valid_ts)
    assert result == "2026-09-21T10:30:00Z"

    valid_offset = "2026-09-21T16:00:00+05:30"
    result_utc = _validate_utc_timestamp(valid_offset)
    assert result_utc == "2026-09-21T10:30:00Z"


def test_cli_validate_utc_timestamp_invalid() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _validate_utc_timestamp("not-a-timestamp")

    with pytest.raises(argparse.ArgumentTypeError):
        _validate_utc_timestamp("2026-09-21")  # Missing time & timezone


def test_cli_validate_session_id_valid() -> None:
    assert _validate_session_id("PRE_OPEN") == "PRE_OPEN"
    assert _validate_session_id("INTRADAY") == "INTRADAY"
    assert _validate_session_id("CLOSE") == "CLOSE"
    assert _validate_session_id("session-01") == "SESSION-01"


def test_cli_validate_session_id_invalid() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _validate_session_id("")

    with pytest.raises(argparse.ArgumentTypeError):
        _validate_session_id("session with spaces")


def test_cli_validate_strategy_id_valid() -> None:
    assert _validate_strategy_id("CR-01") == "CR-01"
    assert _validate_strategy_id("TN-01") == "TN-01"
    assert _validate_strategy_id("OR-01") == "OR-01"
    assert _validate_strategy_id("FD-01") == "FD-01"
    assert _validate_strategy_id("GV-01") == "GV-01"
    assert _validate_strategy_id("CL-01") == "CL-01"


def test_cli_validate_strategy_id_invalid() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _validate_strategy_id("INVALID_NAME")

    with pytest.raises(argparse.ArgumentTypeError):
        _validate_strategy_id("12345")
