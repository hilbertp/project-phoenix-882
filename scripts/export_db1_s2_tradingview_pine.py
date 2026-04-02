from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_s2_tradingview_pine_read.service import (
    DB1S2TradingViewPineReadService,
    PINE_ARTIFACT_FILENAME,
)


def main() -> None:
    payload = DB1S2TradingViewPineReadService().get_pine_review_payload()
    artifact_path = Path("artifacts/discovery_bet_1") / PINE_ARTIFACT_FILENAME
    artifact_path.write_text(str(payload["pine_script"]), encoding="utf-8")
    print(artifact_path)


if __name__ == "__main__":
    main()