#!/usr/bin/env python3
"""
Arrow coherence check for this project's LID docs (docs/intent, docs/arrows).

Deterministic checks only; declared under `## LID Tooling` in AGENTS.md so
/arrow-maintenance can delegate to it instead of auditing in-prompt.

  1. Reference coherence  - arrow-doc paths, spec IDs, and line ranges resolve
  2. Coverage             - every spec cited from code; test citations reported
  3. Markers              - specs still marked `[ ]` (open gaps) are listed
  4. Drift                - reverse orphans (@spec IDs with no spec); tests
                            without a @spec annotation
  5. Orphans              - design docs, spec files, or annotated code files not
                            referenced from any arrow doc

Exit status is 1 when a hard finding exists (1, 4, 5); coverage and marker
output is informational, since some specs are verified by running rather
than by unit tests (see docs/high-level-design.md, Key Design Decisions).

Usage: uv run python scripts/check_coherence.py
"""

import glob
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

ID_RE = re.compile(r"\b([A-Z]+-[A-Z]+-\d{3})\b")
SPEC_LINE_RE = re.compile(r"- \[(x| |D)\] \*\*([A-Z-0-9]+)\*\*")
PATH_RE = re.compile(r"^- ([A-Za-z0-9_./-]+\.(?:md|py|yml|yaml|json|toml))", re.M)
BARE_FILE_RE = re.compile(
    r"^- (Dockerfile|docker-compose\.yml|renovate\.json|osv-scanner\.toml|\.flake8)",
    re.M,
)
LINE_RANGE_RE = re.compile(r"`?([a-z_./]+\.py):(\d+)(?:-(\d+))?`?")

SEGMENTS = sorted(
    os.path.basename(d) for d in glob.glob("docs/intent/*") if os.path.isdir(d)
)
CODE_FILES = (
    sorted(glob.glob("*.py"))
    + sorted(glob.glob(".github/workflows/*.yml"))
    + ["Dockerfile", "docker-compose.yml"]
)
TEST_FILES = sorted(glob.glob("tests/test_*.py"))

hard_findings = 0


def finding(msg: str) -> None:
    global hard_findings
    hard_findings += 1
    print(f"  FINDING: {msg}")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def line_count(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def load_specs() -> dict:
    specs = {}
    for seg in SEGMENTS:
        path = f"docs/intent/{seg}/{seg}-specs.md"
        if not os.path.exists(path):
            continue
        for line in read(path).splitlines():
            m = SPEC_LINE_RE.match(line)
            if m:
                specs[m.group(2)] = (seg, m.group(1))
    return specs


def cited_ids(path: str) -> set:
    return set(ID_RE.findall(read(path)))


def _check_arrow_doc(seg: str, doc: str, specs: dict, hld: str) -> None:
    for ref in PATH_RE.findall(doc) + BARE_FILE_RE.findall(doc):
        if not os.path.exists(ref.split(":")[0]):
            finding(f"{seg}: reference rot - {ref} does not exist")
    for sid in ID_RE.findall(doc):
        if sid not in specs:
            finding(f"{seg}: arrow doc cites unknown spec {sid}")
    for m in LINE_RANGE_RE.finditer(doc):
        path, start, end = m.group(1), int(m.group(2)), m.group(3)
        if not os.path.exists(path):
            continue
        last = int(end) if end else start
        if last > line_count(path):
            finding(
                f"{seg}: line range {path}:{start}-{last} exceeds file length {line_count(path)}"
            )
    m = re.search(r"docs/high-level-design.md \(([A-Z][A-Za-z ]+?)[:)]", doc)
    if m and f"## {m.group(1).strip()}" not in hld:
        finding(f"{seg}: HLD section '{m.group(1).strip()}' not found")


def check_references(specs: dict) -> None:
    print("## 1. Reference coherence")
    hld = (
        read("docs/high-level-design.md")
        if os.path.exists("docs/high-level-design.md")
        else ""
    )
    for seg in SEGMENTS:
        doc_path = f"docs/arrows/{seg}.md"
        if not os.path.exists(doc_path):
            finding(f"{seg}: arrow doc {doc_path} missing")
            continue
        _check_arrow_doc(seg, read(doc_path), specs, hld)


def check_coverage(specs: dict, code_cites: dict, test_cites: dict) -> None:
    print("## 2. Coverage (informational)")
    all_test = set().union(*test_cites.values()) if test_cites else set()
    all_code = set().union(*code_cites.values()) if code_cites else set()
    for seg in SEGMENTS:
        untested = sorted(
            s for s, (g, _) in specs.items() if g == seg and s not in all_test
        )
        print(
            f"  {seg}: {len(untested)} spec(s) without a test citation"
            + (": " + " ".join(untested) if untested else "")
        )
    nocode = sorted(s for s in specs if s not in all_code)
    print(f"  specs without a code citation: {' '.join(nocode) or 'none'}")


def check_markers(specs: dict) -> None:
    print("## 3. Markers")
    for seg in SEGMENTS:
        c = Counter(st for s, (g, st) in specs.items() if g == seg)
        gaps = sorted(s for s, (g, st) in specs.items() if g == seg and st == " ")
        print(
            f"  {seg}: implemented={c['x']} gaps={c[' ']} deferred={c['D']}"
            + (" -> " + " ".join(gaps) if gaps else "")
        )


def check_drift(specs: dict, code_cites: dict, test_cites: dict) -> None:
    print("## 4. Drift signals")
    for sid in sorted(set().union(*code_cites.values(), *test_cites.values())):
        if sid not in specs:
            finding(f"reverse orphan: @spec {sid} has no spec")
    for path in TEST_FILES:
        src = read(path).split("\n")
        for i, line in enumerate(src):
            if not re.match(r"\s+def test_", line):
                continue
            # walk up over (possibly multi-line) decorators to the preceding blank line
            j = i
            while (
                j > 0
                and src[j - 1].strip()
                and not re.match(r"\s*(def |class )", src[j - 1])
            ):
                j -= 1
            if not any(ln.strip().startswith("# @spec") for ln in src[j:i]):
                finding(f"test without @spec: {path}:{i + 1} {line.strip()[4:64]}")


def check_orphans(code_cites: dict) -> None:
    print("## 5. Orphan artifacts")
    all_arrow = "".join(
        read(f"docs/arrows/{s}.md")
        for s in SEGMENTS
        if os.path.exists(f"docs/arrows/{s}.md")
    )
    for path in glob.glob("docs/intent/*/*.md"):
        if path not in all_arrow:
            finding(f"orphan: {path} not referenced from any arrow doc")
    for path, ids in code_cites.items():
        if ids and path not in all_arrow and os.path.basename(path) not in all_arrow:
            finding(f"orphan: {path} carries @spec but is in no arrow doc References")


def main() -> int:
    specs = load_specs()
    code_cites = {f: cited_ids(f) for f in CODE_FILES if os.path.exists(f)}
    test_cites = {f: cited_ids(f) for f in TEST_FILES}
    check_references(specs)
    check_coverage(specs, code_cites, test_cites)
    check_markers(specs)
    check_drift(specs, code_cites, test_cites)
    check_orphans(code_cites)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    print(
        f"\n{len(specs)} specs, {len(SEGMENTS)} segments, HEAD {head[:7]}: "
        + ("clean" if hard_findings == 0 else f"{hard_findings} hard finding(s)")
    )
    return 1 if hard_findings else 0


if __name__ == "__main__":
    sys.exit(main())
