from datetime import datetime, timedelta, timezone


def activity_since() -> datetime:
    """Return the activity cutoff: 24h ago on Tue–Sun, or last Friday at this time on Monday."""
    now = datetime.now(timezone.utc)
    if now.weekday() == 0:  # Monday
        return now - timedelta(days=3)
    return now - timedelta(hours=24)
