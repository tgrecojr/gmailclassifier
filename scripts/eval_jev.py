#!/usr/bin/env python3
"""
Evaluate the Jev classifier on a hand-labeled JSONL sample and sweep thresholds.

    uv run python scripts/eval_jev.py data/jev_sample.jsonl

Rows come from scripts/dump_sample.py (fields: id, subject, from, date, body,
expected_labels). Raw Jev answers are cached next to the sample
(<sample>.answers.jsonl) so re-running a sweep costs nothing.

Credentials/endpoint come from .env exactly as for the agent: OPENROUTER_API_KEY
(a LiteLLM virtual key when LLM_BASE_URL points at the proxy), LLM_BASE_URL,
and optional JEV_DECISIONS_URL / JEV_MODEL overrides.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_classifier import (  # noqa: E402
    DEFAULT_MODEL,
    JevClassifier,
    JevRequestError,
    decisions_url_for,
    question_key,
    select_labels,
)

OFF = 2.0  # a confidence threshold no answer can reach: disables the fallback


def load_label_config(path: str) -> tuple[list[str], dict[str, str]]:
    """labels + label_descriptions from classifier_config.json (no config import:
    importing config loads the live classifier_config.json as a side effect)."""
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    return list(cfg["labels"]), dict(cfg.get("label_descriptions") or {})


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def build_classifier(labels: list[str], descriptions: dict[str, str]) -> JevClassifier:
    base_url = os.getenv("LLM_BASE_URL", "").strip() or "https://openrouter.ai/api/v1"
    url = os.getenv("JEV_DECISIONS_URL", "").strip() or decisions_url_for(base_url)
    return JevClassifier(
        api_key=os.environ["OPENROUTER_API_KEY"],
        labels=labels,
        label_descriptions=descriptions,
        model=os.getenv("JEV_MODEL", DEFAULT_MODEL),
        decisions_url=url,
    )


def fetch_answers(rows: list[dict], cache_path: Path, classifier) -> dict[str, dict]:
    """Return id -> answers, calling Jev only for rows missing from the cache."""
    cached = {r["id"]: r for r in read_jsonl(cache_path)}
    with cache_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            if row["id"] in cached:
                continue
            try:
                answers = classifier.decide(row)
            except JevRequestError as e:
                print(f"  ! {row['id']} failed: {e}", file=sys.stderr)
                continue
            record = {"id": row["id"], "answers": answers}
            cached[row["id"]] = record
            fh.write(json.dumps(record) + "\n")
            print(f"  . {row['subject'][:60]}", file=sys.stderr)
    return {rid: rec["answers"] for rid, rec in cached.items()}


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(rows, answers, labels, threshold, fallback) -> dict:
    tp = fp = fn = exact = 0
    per_label = defaultdict(Counter)
    for row in rows:
        expected = set(row["expected_labels"])
        predicted = set(select_labels(answers[row["id"]], labels, threshold, fallback))
        exact += predicted == expected
        for label in labels:
            e, p = label in expected, label in predicted
            key = "tp" if e and p else "fp" if p else "fn" if e else "tn"
            per_label[label][key] += 1
            tp += e and p
            fp += p and not e
            fn += e and not p
    p, r, f = prf(tp, fp, fn)
    return {"p": p, "r": r, "f1": f, "exact": exact / len(rows), "per_label": per_label}


def print_sweep(rows, answers, labels, thresholds, fallback) -> float:
    print(
        f"\n{'thr':>5} | {'noul only: P':>12} {'R':>6} {'F1':>6} {'exact':>6} | "
        f"{'with fallback: P':>16} {'R':>6} {'F1':>6} {'exact':>6}"
    )
    best_t, best_f = thresholds[0], -1.0
    for t in thresholds:
        a = score(rows, answers, labels, t, OFF)
        b = score(rows, answers, labels, t, fallback)
        print(
            f"{t:>5.2f} | {a['p']:>12.3f} {a['r']:>6.3f} {a['f1']:>6.3f} {a['exact']:>6.2f} | "
            f"{b['p']:>16.3f} {b['r']:>6.3f} {b['f1']:>6.3f} {b['exact']:>6.2f}"
        )
        if b["f1"] > best_f:
            best_t, best_f = t, b["f1"]
    return best_t


def print_per_label(rows, answers, labels, threshold, fallback) -> None:
    result = score(rows, answers, labels, threshold, fallback)
    print(f"\nPer label at threshold {threshold:.2f} (fallback {fallback:.2f}):")
    print(f"{'label':<20} {'tp':>4} {'fp':>4} {'fn':>4} {'P':>6} {'R':>6}")
    for label in labels:
        c = result["per_label"][label]
        p, r, _ = prf(c["tp"], c["fp"], c["fn"])
        print(f"{label:<20} {c['tp']:>4} {c['fp']:>4} {c['fn']:>4} {p:>6.2f} {r:>6.2f}")


def print_histogram(rows, answers, labels) -> None:
    pos, neg = Counter(), Counter()
    for row in rows:
        for label in labels:
            answer = answers[row["id"]].get(question_key(label), {})
            p = answer.get("noul")
            if isinstance(p, (int, float)):
                bucket = min(int(p * 10), 9)
                (pos if label in row["expected_labels"] else neg)[bucket] += 1
    print("\nNoul probability histogram (expected-true vs expected-false):")
    for b in range(10):
        print(f"  {b / 10:.1f}-{(b + 1) / 10:.1f}  true={pos[b]:>4}  false={neg[b]:>4}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sample")
    parser.add_argument(
        "--config",
        default=os.getenv("CLASSIFIER_CONFIG_PATH", "classifier_config.json"),
    )
    parser.add_argument("--thresholds", default="0.5,0.6,0.7,0.8,0.9")
    parser.add_argument("--fallback", type=float, default=0.5)
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()
    load_dotenv(args.env)

    labels, descriptions = load_label_config(args.config)

    sample = Path(args.sample)
    rows = [r for r in read_jsonl(sample) if r.get("expected_labels") is not None]
    if not rows:
        print(
            "No rows with expected_labels; run scripts/dump_sample.py and label them."
        )
        return 1
    classifier = build_classifier(labels, descriptions)
    answers = fetch_answers(rows, sample.with_suffix(".answers.jsonl"), classifier)
    rows = [r for r in rows if r["id"] in answers]
    print(
        f"\n{len(rows)} emails, {len(labels)} labels, endpoint {classifier.decisions_url}"
    )

    thresholds = [float(t) for t in args.thresholds.split(",")]
    best = print_sweep(rows, answers, labels, thresholds, args.fallback)
    print_per_label(rows, answers, labels, best, args.fallback)
    print_histogram(rows, answers, labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
