from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_fib_review_pine_read.service import (
    DB1FibReviewPineReadService,
    PINE_ARTIFACT_FILENAME,
)


def main() -> None:
    payload = DB1FibReviewPineReadService().get_pine_review_payload(
        include_debug_rejected=False
    )
    artifact_path = Path("artifacts/discovery_bet_1") / PINE_ARTIFACT_FILENAME
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(str(payload["pine_script"]), encoding="utf-8")
    print(artifact_path)
    print(f"accepted_structures={payload['accepted_structure_count']}")
    print(f"debug_rejected={payload['debug_rejected_count']}")


if __name__ == "__main__":
    main()
