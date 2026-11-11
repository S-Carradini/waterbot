"""
Regenerate eval/aliases.yaml from CONTENT-HASH evidence.

WHY CONTENT, NOT FILENAMES
--------------------------
The first version of aliases.yaml was built from filename similarity, so every
group was a guess marked verified: false. The corpus carries a content_hash per
chunk, which gives hard proof instead: two document names whose complete set of
chunk hashes is identical hold byte-identical text.

That is the right criterion for RETRIEVAL SCORING specifically. When two names
hold identical content, the retriever cannot distinguish them by any means —
the vectors are the same. Scoring them as different documents penalises the
retriever for something no retriever could ever get right. Grouping them makes
recall measure retrieval instead of corpus hygiene.

WHAT THIS DOES NOT DO
---------------------
Grouping identical content for scoring is NOT a claim that the underlying
documents are the same work. Two causes produce identical content:

  ALIAS       one document ingested under several names (harmless)
  CORRUPTION  different documents whose stored text is identical because the
              wrong file was downloaded — e.g. Tribal Water Study chapters
              5.1-5.9 each contain the entire report instead of their chapter

Corruption is a real corpus defect that affects production answers and must be
fixed by re-acquiring the source files. Grouping it here stops it distorting
the metric; it does not repair it. Suspected corruption is written to
eval/results/corpus_defects.md so it stays visible.

USAGE
    python eval/generate_aliases.py            # preview
    python eval/generate_aliases.py --write    # rewrite aliases.yaml
"""

import argparse
import os
import re
import sys
from typing import Dict, List

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.config import resolve_db_url
from eval.preflight import fetch_content_duplication

ALIAS_PATH = os.path.join(_script_dir, "aliases.yaml")
DEFECTS_PATH = os.path.join(_script_dir, "results", "corpus_defects.md")

# Entity words that, when they DIFFER between two names holding identical
# content, indicate the files are meant to be different documents — i.e.
# corruption rather than an alias.
_ENTITY_HINTS = re.compile(
    r"\b(ute|suit|umut|jicarilla|navajo|mojave|crit|quechan|cocopah|chemehuevi|"
    r"hopi|apache|tohono|yavapai|maricopa|pima|pinal|gila|graham|cochise|"
    r"coconino|mohave|yuma|la\s*paz|santa\s*cruz|greenlee|benson|prescott|"
    r"tucson|phoenix|chandler|mesa|glendale|scottsdale|flagstaff|wickenburg|"
    r"williams|page|winslow|cottonwood|houston)\b",
    re.IGNORECASE,
)


def _entities(name: str) -> set:
    return {m.group(0).lower().replace(" ", "") for m in _ENTITY_HINTS.finditer(name)}


def classify_cluster(names: List[str]) -> str:
    """SUSPECTED_CORRUPTION when names reference different named entities."""
    entity_sets = [_entities(n) for n in names]
    non_empty = [e for e in entity_sets if e]
    if len(non_empty) >= 2:
        union = set().union(*non_empty)
        intersection = set.intersection(*non_empty)
        if union - intersection:
            return "SUSPECTED_CORRUPTION"
    return "LIKELY_ALIAS"


def canonical_for(names: List[str]) -> str:
    """Pick the most descriptive name: longest, tie-broken alphabetically."""
    return sorted(names, key=lambda n: (-len(n), n))[0]


def _yaml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build(clusters: List[dict]) -> str:
    lines = [
        "# Document alias groups — GENERATED FROM CONTENT HASHES.",
        "#",
        "# Regenerate with: python eval/generate_aliases.py --write",
        "#",
        "# Every group below is PROVEN: all member names hold a byte-identical set",
        "# of chunk content hashes, so the retriever cannot distinguish them by any",
        "# means. Grouping them makes recall measure retrieval rather than corpus",
        "# hygiene. verified: true reflects that content-hash proof.",
        "#",
        "# IMPORTANT: a group marked SUSPECTED_CORRUPTION is NOT a claim that the",
        "# documents are the same work. It means different documents currently hold",
        "# identical stored text because the wrong file was ingested. Grouping stops",
        "# it distorting the metric; the corpus still needs repairing. See",
        "# eval/results/corpus_defects.md.",
        "#",
        "# Do not hand-edit: this file is regenerated from the corpus.",
        "",
        "alias_groups:",
    ]

    for c in sorted(clusters, key=lambda x: -x["redundant_chunks"]):
        names = c["documents"]
        kind = classify_cluster(names)
        canonical = canonical_for(names)
        lines.append(f"  - canonical_id: {_yaml_quote(canonical)}")
        lines.append(f"    verified: true")
        lines.append(f"    evidence: content_hash_identical")
        lines.append(f"    classification: {kind}")
        lines.append(f"    chunks_each: {c['chunks_each']}")
        lines.append(f"    content_fingerprint: {c['fingerprint'][:16]}")
        lines.append(f"    members:")
        for n in names:
            lines.append(f"      - {_yaml_quote(n)}")
        lines.append("")

    return "\n".join(lines)


def build_defect_report(clusters: List[dict]) -> str:
    corrupt = [c for c in clusters if classify_cluster(c["documents"]) == "SUSPECTED_CORRUPTION"]
    total_docs = sum(c["document_count"] for c in corrupt)
    wasted = sum(c["redundant_chunks"] for c in corrupt)

    lines = [
        "# Corpus Defects — Suspected Content Corruption",
        "",
        "Generated by `python eval/generate_aliases.py`.",
        "",
        "Each cluster below contains document names that reference **different named "
        "entities** (different tribes, cities, or counties) yet hold **byte-identical "
        "stored content**. That means the wrong file was ingested under these names.",
        "",
        "**This affects production answers, not just evaluation.** A user asking about "
        "one entity is served text stored under all of them, and the duplicates consume "
        "multiple slots in the top-k, crowding out genuinely different sources.",
        "",
        f"- Clusters: **{len(corrupt)}**",
        f"- Document names affected: **{total_docs}**",
        f"- Redundant chunks: **{wasted:,}**",
        "",
        "## Fix",
        "",
        "Re-acquire each source file, verify the files differ before ingesting "
        "(compare checksums), then re-ingest. Verified example: the eight Tribal Water "
        "Study chapters each contain the *entire* report (773 chunks) instead of their "
        "own chapter, while `Ch.-5.10-Cocopah` downloaded correctly at 27 chunks — "
        "proving the failure was per-download, not a pipeline fault.",
        "",
        "## Clusters",
        "",
        "| Docs | Chunks each | Redundant | Names |",
        "|------|-------------|-----------|-------|",
    ]
    for c in sorted(corrupt, key=lambda x: -x["redundant_chunks"]):
        names = "<br>".join(c["documents"])
        lines.append(f"| {c['document_count']} | {c['chunks_each']} | {c['redundant_chunks']:,} | {names} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite aliases.yaml and the defect report")
    args = parser.parse_args()

    clusters = fetch_content_duplication(resolve_db_url())
    yaml_text = build(clusters)
    defects = build_defect_report(clusters)

    n_corrupt = sum(1 for c in clusters if classify_cluster(c["documents"]) == "SUSPECTED_CORRUPTION")
    print(f"Clusters: {len(clusters)}  "
          f"(likely alias: {len(clusters) - n_corrupt}, suspected corruption: {n_corrupt})")
    print(f"Document names covered: {sum(c['document_count'] for c in clusters)}")

    if args.write:
        with open(ALIAS_PATH, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        os.makedirs(os.path.dirname(DEFECTS_PATH), exist_ok=True)
        with open(DEFECTS_PATH, "w", encoding="utf-8") as f:
            f.write(defects)
        print(f"Wrote {ALIAS_PATH}")
        print(f"Wrote {DEFECTS_PATH}")
    else:
        print("\n(preview — pass --write to apply)")
        print(yaml_text[:1200])

    return 0


if __name__ == "__main__":
    sys.exit(main())
