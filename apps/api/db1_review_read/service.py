from __future__ import annotations

from pathlib import Path

from apps.api.db1_review_read.artifact_reader import load_review_artifacts
from apps.api.db1_review_read.models import ReviewProgress, ReviewReadResponse

DEFAULT_ARTIFACTS_DIR = Path("artifacts/discovery_bet_1")


class InvalidReviewRequestError(Exception):
    """The caller supplied an invalid DB1 review read query."""


class ReviewStructureNotFoundError(Exception):
    """The requested DB1 review structure does not exist."""


class DB1ReviewReadService:
    def __init__(self, artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR) -> None:
        self._artifacts_dir = artifacts_dir

    def get_review_payload(
        self,
        *,
        index: int | None = None,
        position: int | None = None,
    ) -> ReviewReadResponse:
        resolved_index = _resolve_index(index=index, position=position)
        bundle = load_review_artifacts(self._artifacts_dir)

        if not bundle.structures:
            raise ReviewStructureNotFoundError("No DB1 fib structures are available.")

        if resolved_index >= len(bundle.structures):
            raise ReviewStructureNotFoundError(
                f"DB1 review structure index {resolved_index} is out of range."
            )

        current_structure = bundle.structures[resolved_index]
        previous_structure = (
            bundle.structures[resolved_index - 1] if resolved_index > 0 else None
        )
        progress = ReviewProgress(
            current_index=resolved_index,
            current_position=resolved_index + 1,
            total_structures=len(bundle.structures),
            label=(f"structure {resolved_index + 1} of {len(bundle.structures)}"),
        )
        return ReviewReadResponse(
            market_contract=bundle.manifest.market_contract,
            progress=progress,
            current_structure=current_structure,
            previous_structure=previous_structure,
        )


def _resolve_index(*, index: int | None, position: int | None) -> int:
    if (index is None and position is None) or (
        index is not None and position is not None
    ):
        raise InvalidReviewRequestError("Provide exactly one of index or position.")

    if index is not None:
        if index < 0:
            raise InvalidReviewRequestError("index must be zero or greater.")
        return index

    assert position is not None
    if position <= 0:
        raise InvalidReviewRequestError("position must be one or greater.")
    return position - 1
