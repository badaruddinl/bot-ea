from __future__ import annotations

from datetime import datetime, timezone


def server_wall_to_mt5_datetime(
    value: datetime,
    server_timezone: timezone,
) -> datetime:
    """Encode a broker wall-clock label for this terminal's MT5 history API."""
    if value.tzinfo is None:
        raise ValueError("MT5 history bounds must be timezone-aware")
    return value.astimezone(server_timezone).replace(tzinfo=timezone.utc)


def mt5_epoch_to_server_wall(
    epoch_seconds: int,
    server_timezone: timezone,
) -> datetime:
    """Decode this broker's epoch fields without applying the offset twice."""
    encoded = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return encoded.replace(tzinfo=server_timezone)
