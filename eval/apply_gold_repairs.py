"""
Apply the reviewed gold_source_id repairs to benchmark_dataset.json.

This is a script rather than a hand-edit so the change is auditable,
reproducible, and reviewable in a diff. It backs up the original, records
provenance on every question it touches, and refuses to invent ground truth.

THE THREE REPAIR CLASSES
------------------------
DROP_ABSENT   The question still has at least one gold source that genuinely
              exists in the corpus. The absent id is simply removed. No
              judgement is required and nothing is invented — this is the
              safest class and covers 9 of the 17 affected questions.

REPLACE       The question had no surviving gold source, AND a corpus document
              was verified to contain substantive content on the topic
              (measured by mention density of the defining term, not by asking
              the retriever). Each replacement records its evidence.

QUARANTINE    The question had no surviving gold source and the corpus does NOT
              contain a document that genuinely serves as a source for it.
              Rather than fabricate a gold source — which would recreate the
              original defect of treating an unverified assumption as ground
              truth — the question is flagged excluded_from_scoring with a
              reason. It stays in the file as a visible TODO: acquire the
              source document, then re-enable.

WHY NOT USE THE RETRIEVER TO PICK REPLACEMENTS
----------------------------------------------
Adopting whatever the retriever returns as the new gold set would force recall
toward 1.0 and permanently destroy the benchmark's ability to detect a
regression. Candidates were therefore found with lexical evidence, which is a
different mechanism from the dense retriever under test.
"""

import datetime
import json
import os
import shutil
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(_script_dir, "benchmark_dataset.json")

REVIEWER = "eval-harness-repair"
REVIEW_DATE = datetime.date.today().isoformat()
NEW_VERSION = "0.2.0-repaired"

# --- Class 1: remove absent ids; other valid gold sources remain -------------
DROP_ABSENT = {
    "q004": ["AMWUA_droughtandshortage.pdf"],
    "q005": ["CAGRD.pdf"],
    "q007": ["Conservation: Agriculture.pdf"],
    "q010": ["reclaimed_wastewater.pdf", "Recycled Water.pdf"],
    "q011": ["Final_AWBA_2022_Annual_Report-10_Year_Plan_with_letter_0.pdf"],
    "q039": ["Colorado River Shortage Status 2023.pdf"],
    "q041": ["Gila river - water settlement.pdf"],
    "q042": ["AMWUA_droughtandshortage.pdf"],
    "q045": ["Water and Land Use in Central Arizona.pdf"],
}

# --- Class 2: verified replacements, with the evidence that justifies them ---
REPLACE = {
    "q009": {
        "remove": ["howToXeriscape.pdf", "Make Low-Water Use Plants a High Priority.pdf"],
        "add": ["Lake Havasu Water Savers.pdf"],
        "evidence": "18 mentions of 'xeriscap' — highest density in the corpus; "
                    "the document is a municipal water-conservation programme guide.",
    },
    "q012": {
        "remove": ["desalination.pdf"],
        "add": ["Strategic Vision for Water Supply.pdf"],
        "evidence": "34 mentions of 'desalination' — highest in the corpus; the "
                    "document has a dedicated augmentation/desalination section.",
    },
    "q014": {
        "remove": ["Long-term Storage Credits.pdf"],
        "add": ["Assured water supply (CAGRD and Replenishment).pdf",
                "Pinal Active Management Area.pdf"],
        "evidence": "15 and 17 mentions of 'long-term storage credit'; both documents "
                    "describe the credit mechanism directly.",
    },
    "q033": {
        "remove": ["arizonawaterfacts.pdf", "doWeHaveEnough.pdf"],
        "add": ["Strategic Vision for Water Supply.pdf"],
        "evidence": "4 chunks carrying an Arizona water-supply percentage breakdown "
                    "including the groundwater share.",
    },
    "q024": {
        "remove": ["Fort Mojave Indian Tribe.pdf"],
        "add": ["Fort Mojave Indian Tribe-2.pdf"],
        "evidence": "Corpus contains 'Fort Mojave Indian Tribe-2.pdf' (35 chunks); the "
                    "un-suffixed name does not exist. The '-2' is a duplicate-copy "
                    "marker on the same subject. Content differs from the un-suffixed "
                    "file, so this is a name correction in the dataset rather than an "
                    "alias — content-hash proof cannot bridge names whose text differs.",
    },
}

# --- Class 3: corpus genuinely lacks a source; do not fabricate one ----------
QUARANTINE = {
    "q017": "Corpus has no document describing the Gila River Indian Community water "
            "settlement itself; matches are passing references inside AMA plans. "
            "Acquire the settlement document, then re-enable.",
    "q018": "Best lexical matches (tribal clean water.pdf / Report.pdf / Universal "
            "Access...) are one corrupted duplicate cluster about tribal clean-water "
            "access, not the Pima-Maricopa Irrigation Project. Acquire the source.",
    "q021": "Arizona Water Innovation Initiative appears in only 4 documents, 13 times "
            "total, all passing references. No document serves as a source.",
    "q023": "AMWUA appears mainly inside Legislative Session Summaries, which record "
            "its positions but do not describe the organisation. Acquire an AMWUA "
            "overview document.",
}


def main() -> int:
    with open(DATASET, "r", encoding="utf-8") as f:
        data = json.load(f)

    backup = DATASET.replace(".json", f".backup-{REVIEW_DATE}.json")
    if not os.path.exists(backup):
        shutil.copy2(DATASET, backup)
        print(f"Backed up original -> {os.path.basename(backup)}")

    changed = 0
    for q in data.get("questions", []):
        qid = q.get("id")
        sources = list(q.get("gold_source_ids", []) or [])
        original = list(sources)

        if qid in DROP_ABSENT:
            for s in DROP_ABSENT[qid]:
                if s in sources:
                    sources.remove(s)
            q["repair"] = {
                "action": "drop_absent",
                "removed": DROP_ABSENT[qid],
                "rationale": "Source absent from corpus; question retains other valid gold sources.",
                "reviewed_by": REVIEWER, "reviewed_on": REVIEW_DATE,
                "original_gold_source_ids": original,
            }
            changed += 1

        elif qid in REPLACE:
            spec = REPLACE[qid]
            for s in spec["remove"]:
                if s in sources:
                    sources.remove(s)
            for s in spec["add"]:
                if s not in sources:
                    sources.append(s)
            q["repair"] = {
                "action": "replace",
                "removed": spec["remove"], "added": spec["add"],
                "evidence": spec["evidence"],
                "rationale": "Replacement selected by lexical mention-density, not by the "
                             "retriever under test, to avoid circular ground truth.",
                "reviewed_by": REVIEWER, "reviewed_on": REVIEW_DATE,
                "original_gold_source_ids": original,
            }
            changed += 1

        elif qid in QUARANTINE:
            q["excluded_from_scoring"] = True
            q["exclusion_reason"] = QUARANTINE[qid]
            q["repair"] = {
                "action": "quarantine",
                "rationale": "No corpus document genuinely sources this question. Excluded "
                             "rather than assigned a fabricated gold source.",
                "reviewed_by": REVIEWER, "reviewed_on": REVIEW_DATE,
                "original_gold_source_ids": original,
            }
            changed += 1

        q["gold_source_ids"] = sources

    meta = data.setdefault("_meta", {})
    meta["version"] = NEW_VERSION
    meta["status"] = (
        "REPAIRED — gold_source_ids validated against the corpus. "
        "Gold ANSWERS remain unverified; see gold_answer_review_status."
    )
    meta["gold_answer_review_status"] = "NOT YET HUMAN-VERIFIED"
    meta["repaired_on"] = REVIEW_DATE
    meta["repair_summary"] = {
        "drop_absent": len(DROP_ABSENT),
        "replace": len(REPLACE),
        "quarantine": len(QUARANTINE),
        "questions_changed": changed,
    }
    meta["notes"] = (
        "gold_source_ids were originally authored from knowledge_sources.py (a URL/citation "
        "mapping, 503 entries) rather than from the vector store (366 documents), so 19 named "
        "documents did not exist in the corpus. Repaired via eval/apply_gold_repairs.py. "
        "Quarantined questions carry excluded_from_scoring=true and are pending source acquisition."
    )

    with open(DATASET, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Repaired {changed} question(s):")
    print(f"  drop_absent : {len(DROP_ABSENT)}")
    print(f"  replace     : {len(REPLACE)}")
    print(f"  quarantine  : {len(QUARANTINE)}")
    print(f"Dataset version -> {NEW_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
