import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))                 # live_helpers
sys.path.insert(0, str(HERE.parents[1]))      # project root (so `import app...` works)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", '  "Bearer test-token"  ')
    monkeypatch.setenv("LIVE_FEED_ENABLED", "true")
