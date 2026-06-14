from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def ist_now_factory():
    def make(h, m, s=0):
        return lambda: datetime(2026, 6, 12, h, m, s, tzinfo=IST)
    return make
