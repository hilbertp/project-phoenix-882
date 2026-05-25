"""Human-in-the-loop review labels for DB1 fib setups, and override application.

The review controller (scripts/review_fibs_tradingview.py) appends one JSON line
per human verdict to ``data/discovery_bet_1/human_labels.jsonl``. The detector
consumes them two ways:

- ``apply_overrides(legs)`` rewrites a raw detected leg list to match the human
  verdicts (drop rejects, replace adjusted anchors) -- the "remember" half.
- the accepted + adjusted records form the ground-truth set the parameter sweep
  tunes against (scripts/calibrate_detector.py) -- the "retune" half.

A label is matched to a raw leg by ``setup_key`` = ``"{parent_ts}|{term_ts}"`` of
the leg the human reviewed, so overrides apply deterministically while detector
parameters are fixed. After a retune changes the raw legs, the labels still serve
as the tuning target even though exact-key overrides may no longer line up.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LABELS_PATH = REPO_ROOT / "data" / "discovery_bet_1" / "human_labels.jsonl"

VERDICT_ACCEPT = "accept"
VERDICT_REJECT = "reject"
VERDICT_ADJUST = "adjust"
VERDICTS = (VERDICT_ACCEPT, VERDICT_REJECT, VERDICT_ADJUST)

ANCHOR_FIELDS = (
    "direction",
    "parent_ts",
    "parent_price",
    "parent_kind",
    "term_ts",
    "term_price",
    "term_kind",
)


@dataclass
class LabelRecord:
    setup_key: str
    verdict: str
    direction: str
    parent_ts: str
    parent_price: float
    term_ts: str
    term_price: float
    corrected: dict | None
    detector_params: dict
    created_at: str


def setup_key(parent_ts: str, term_ts: str) -> str:
    """Stable identity for a raw setup, independent of price/direction."""
    return f"{parent_ts}|{term_ts}"


def make_label(
    leg: dict,
    verdict: str,
    *,
    corrected: dict | None = None,
    detector_params: dict | None = None,
) -> LabelRecord:
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}; expected one of {VERDICTS}")
    if verdict == VERDICT_ADJUST and not corrected:
        raise ValueError("an 'adjust' verdict requires corrected anchors")
    return LabelRecord(
        setup_key=setup_key(leg["parent_ts"], leg["term_ts"]),
        verdict=verdict,
        direction=leg["direction"],
        parent_ts=leg["parent_ts"],
        parent_price=float(leg["parent_price"]),
        term_ts=leg["term_ts"],
        term_price=float(leg["term_price"]),
        corrected=corrected,
        detector_params=detector_params or {},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def load_labels(path: Path = LABELS_PATH) -> list[LabelRecord]:
    if not path.exists():
        return []
    records: list[LabelRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(LabelRecord(**json.loads(line)))
    return records


def latest_by_key(labels: list[LabelRecord]) -> dict[str, LabelRecord]:
    """Last verdict per setup_key wins (the file is append-only history)."""
    latest: dict[str, LabelRecord] = {}
    for label in labels:
        latest[label.setup_key] = label
    return latest


def append_label(record: LabelRecord, path: Path = LABELS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record)) + "\n")


def apply_overrides(
    legs: list[dict],
    labels: list[LabelRecord] | None = None,
    path: Path = LABELS_PATH,
) -> list[dict]:
    """Rewrite a raw detected leg list to honour the latest human verdicts.

    reject -> drop the leg; adjust -> replace its anchor fields with the corrected
    ones; accept (or no label) -> keep as-is. Returns a new list; inputs untouched.
    """
    if labels is None:
        labels = load_labels(path)
    verdicts = latest_by_key(labels)
    out: list[dict] = []
    for leg in legs:
        label = verdicts.get(setup_key(leg["parent_ts"], leg["term_ts"]))
        if label is None or label.verdict == VERDICT_ACCEPT:
            out.append(leg)
            continue
        if label.verdict == VERDICT_REJECT:
            continue
        merged = dict(leg)
        for field in ANCHOR_FIELDS:
            if label.corrected and field in label.corrected:
                merged[field] = label.corrected[field]
        out.append(merged)
    return out


def truth_setups(
    labels: list[LabelRecord] | None = None, path: Path = LABELS_PATH
) -> list[dict]:
    """Human-approved setups (accept -> original, adjust -> corrected). Rejects
    are excluded. This is the ground-truth target for detector calibration."""
    if labels is None:
        labels = load_labels(path)
    out: list[dict] = []
    for label in latest_by_key(labels).values():
        if label.verdict == VERDICT_REJECT:
            continue
        if label.verdict == VERDICT_ADJUST and label.corrected:
            out.append(dict(label.corrected))
        else:
            out.append(
                {
                    "direction": label.direction,
                    "parent_ts": label.parent_ts,
                    "parent_price": label.parent_price,
                    "term_ts": label.term_ts,
                    "term_price": label.term_price,
                }
            )
    return out
