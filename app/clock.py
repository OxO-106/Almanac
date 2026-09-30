from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def local(dt: datetime) -> datetime:
    return dt.astimezone(LA)
