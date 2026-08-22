"""L1: the frozen response store.

WHY FREEZE
----------
The core experiment judges the SAME responses under many panel configurations. If each
configuration re-ran the bot, judge variance would be confounded with generation variance and
with retrieval drift on an approximate index that already differs by ~2 points between identical
runs. Freezing separates them, and makes re-judging free rather than a fresh inference bill.

LAYOUT
------
    eval/results/runs/<corpus_fingerprint>/<run_id>/
        manifest.json                  provenance: fingerprint, versions, judges, cost
        responses/<system>__<persona>.jsonl
        verdicts/<judge_model_id>.jsonl

The fingerprint is in the path, not just the manifest. Runs against different corpora cannot
land in the same directory even by accident, and listing what exists for a corpus is a directory
read rather than a scan of every manifest on disk.

GUARANTEES
----------
* **Responses are write-once.** Re-freezing raises unless ``overwrite=True``, so a stale re-run
  cannot silently invalidate verdicts already recorded against the old responses.
* **Verdicts are append-only**, and every appended verdict must reference a response that exists
  in this run. A verdict pointing at nothing surfaces much later as a mysteriously small sample.
* **The fingerprint is checked on load.** Judging responses frozen against a different corpus
  than the one configured is exactly the contamination L0 exists to prevent.
* **Byte-identical output.** Two freezes of the same inputs produce identical response files:
  canonical JSON, sorted keys, LF newlines, no timestamps inside response records. This is
  milestone 4's acceptance check, and it is what makes "reproducible" mean something stronger
  than "similar".
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

from eval.judge.schemas import Response, RunManifest, Verdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_EVAL_DIR = os.path.dirname(_HERE)
DEFAULT_RUNS_DIR = os.path.join(_EVAL_DIR, "results", "runs")

MANIFEST = "manifest.json"
RESPONSES_DIR = "responses"
VERDICTS_DIR = "verdicts"

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class StoreError(RuntimeError):
    """Raised when the store is asked to do something that would lose or corrupt data."""


class CorpusMismatch(StoreError):
    """Raised when frozen responses came from a different corpus than the one expected."""


def _safe(component: str) -> str:
    """Make a filename component safe without letting two distinct names collide silently."""
    cleaned = _SAFE_COMPONENT.sub("-", component).strip("-")
    if not cleaned:
        raise StoreError(f"{component!r} has no filename-safe characters")
    return cleaned


def _canonical_line(payload: dict) -> str:
    """One JSONL row, canonically encoded.

    Sorted keys and tight separators, so two freezes of the same data are byte-identical rather
    than merely equivalent. ``ensure_ascii=False`` keeps water-policy text readable in the file
    instead of escaping every non-ASCII character.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _write_jsonl(path: str, rows: Iterable[dict], mode: str = "w") -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    count = 0
    # newline="" so Python does not translate \n to \r\n on Windows; the files must be
    # byte-identical across platforms, not merely line-equivalent.
    with open(path, mode, encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(_canonical_line(row))
            handle.write("\n")
            count += 1
    return count


def _read_jsonl(path: str) -> Iterator[dict]:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreError(f"{os.path.basename(path)} line {number} is not valid JSON: {exc}")


class ResponseStore:
    """Read and write access to one frozen run."""

    def __init__(
        self,
        corpus_fingerprint: str,
        run_id: str,
        runs_dir: str = DEFAULT_RUNS_DIR,
    ) -> None:
        if not corpus_fingerprint:
            raise StoreError("a run must be scoped by corpus fingerprint (invariant 1)")
        if not run_id:
            raise StoreError("run_id may not be empty")
        self.corpus_fingerprint = corpus_fingerprint
        self.run_id = run_id
        self.runs_dir = runs_dir
        self.path = os.path.join(runs_dir, _safe(corpus_fingerprint), _safe(run_id))

    # -- paths ------------------------------------------------------------
    @property
    def manifest_path(self) -> str:
        return os.path.join(self.path, MANIFEST)

    @property
    def responses_dir(self) -> str:
        return os.path.join(self.path, RESPONSES_DIR)

    @property
    def verdicts_dir(self) -> str:
        return os.path.join(self.path, VERDICTS_DIR)

    def responses_path(self, system: str, persona: str) -> str:
        return os.path.join(self.responses_dir, f"{_safe(system)}__{_safe(persona)}.jsonl")

    def verdicts_path(self, judge_model_id: str) -> str:
        return os.path.join(self.verdicts_dir, f"{_safe(judge_model_id)}.jsonl")

    def exists(self) -> bool:
        return os.path.exists(self.manifest_path)

    # -- freezing ---------------------------------------------------------
    def freeze(
        self,
        manifest: RunManifest,
        responses: Sequence[Response],
        overwrite: bool = False,
    ) -> int:
        """Write the manifest and responses. Write-once unless ``overwrite`` is set.

        Responses are grouped into one file per ``(system, persona)`` and sorted by item id, so
        the file layout is a function of the data and not of the order it happened to arrive in.
        """
        if not responses:
            raise StoreError("refusing to freeze a run with no responses")

        if manifest.corpus_fingerprint != self.corpus_fingerprint:
            raise CorpusMismatch(
                f"manifest fingerprint {manifest.corpus_fingerprint!r} does not match the "
                f"store's {self.corpus_fingerprint!r}"
            )
        if manifest.run_id != self.run_id:
            raise StoreError(
                f"manifest run_id {manifest.run_id!r} does not match the store's {self.run_id!r}"
            )

        response_ids = [r.response_id for r in responses]
        if len(set(response_ids)) != len(response_ids):
            duplicates = sorted({i for i in response_ids if response_ids.count(i) > 1})
            raise StoreError(f"duplicate response ids in freeze: {duplicates[:5]}")

        if self.exists() and not overwrite:
            raise StoreError(
                f"run {self.run_id!r} is already frozen and runs are immutable (invariant 2). "
                "Pass overwrite=True only to discard it deliberately."
            )
        if self.exists() and overwrite:
            # Verdicts recorded against the old responses would now point at text nobody can
            # see. Removing the whole directory is the honest move; keeping half of it is not.
            shutil.rmtree(self.path)

        os.makedirs(self.responses_dir, exist_ok=True)

        grouped: Dict[tuple, List[Response]] = {}
        for response in responses:
            grouped.setdefault((response.system, response.persona), []).append(response)

        written = 0
        for (system, persona), group in sorted(grouped.items()):
            group.sort(key=lambda r: r.item_id)
            written += _write_jsonl(
                self.responses_path(system, persona),
                (r.model_dump(mode="json") for r in group),
            )

        with open(self.manifest_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(
                json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2,
                           ensure_ascii=False)
            )
            handle.write("\n")

        return written

    # -- reading ----------------------------------------------------------
    def load_manifest(self) -> RunManifest:
        if not self.exists():
            raise StoreError(f"no manifest at {self.manifest_path}")
        with open(self.manifest_path, "r", encoding="utf-8") as handle:
            manifest = RunManifest.model_validate(json.load(handle))
        if manifest.corpus_fingerprint != self.corpus_fingerprint:
            raise CorpusMismatch(
                f"manifest at {self.manifest_path} declares fingerprint "
                f"{manifest.corpus_fingerprint!r}, but it is stored under "
                f"{self.corpus_fingerprint!r}"
            )
        return manifest

    def load_responses(
        self,
        system: Optional[str] = None,
        persona: Optional[str] = None,
        expected_fingerprint: Optional[str] = None,
    ) -> List[Response]:
        """Load frozen responses, optionally filtered, with the corpus check applied.

        ``expected_fingerprint`` is the caller stating which corpus it believes it is judging
        against. A mismatch raises rather than warns: silently judging responses from another
        corpus produces numbers that look completely normal.
        """
        if expected_fingerprint is not None and expected_fingerprint != self.corpus_fingerprint:
            raise CorpusMismatch(
                f"caller expected corpus {expected_fingerprint!r}, store holds "
                f"{self.corpus_fingerprint!r}"
            )
        if not os.path.isdir(self.responses_dir):
            raise StoreError(f"no responses directory at {self.responses_dir}")

        responses: List[Response] = []
        for filename in sorted(os.listdir(self.responses_dir)):
            if not filename.endswith(".jsonl"):
                continue
            path = os.path.join(self.responses_dir, filename)
            for row in _read_jsonl(path):
                response = Response.model_validate(row)
                if system is not None and response.system != system:
                    continue
                if persona is not None and response.persona != persona:
                    continue
                responses.append(response)

        responses.sort(key=lambda r: r.response_id)
        return responses

    def response_ids(self) -> set:
        return {r.response_id for r in self.load_responses()}

    def pairs(self) -> List[tuple]:
        """The (system, persona) pairs this run holds."""
        if not os.path.isdir(self.responses_dir):
            return []
        found = set()
        for filename in sorted(os.listdir(self.responses_dir)):
            if filename.endswith(".jsonl") and "__" in filename:
                system, persona = filename[: -len(".jsonl")].split("__", 1)
                found.add((system, persona))
        return sorted(found)

    # -- verdicts ---------------------------------------------------------
    def append_verdicts(self, verdicts: Sequence[Verdict], validate: bool = True) -> int:
        """Append verdicts. Never rewrites, never silently deduplicates.

        A ``(response_id, judge_model_id, sample_index)`` triple identifies one vote. Appending
        the same triple twice is refused rather than dropped: a double-counted vote falsely
        narrows the confidence interval, and dropping one silently would quietly reduce k. Both
        are failures, so the write raises and the caller decides.
        """
        if not verdicts:
            return 0
        if not self.exists():
            raise StoreError("cannot append verdicts to a run that has not been frozen")

        if validate:
            known = self.response_ids()
            unknown = sorted({v.response_id for v in verdicts if v.response_id not in known})
            if unknown:
                raise StoreError(
                    f"{len(unknown)} verdict(s) reference responses not in this run, "
                    f"e.g. {unknown[:3]}. A verdict pointing at nothing surfaces later as a "
                    "mysteriously small sample."
                )
            wrong_corpus = sorted(
                {v.corpus_fingerprint for v in verdicts
                 if v.corpus_fingerprint != self.corpus_fingerprint}
            )
            if wrong_corpus:
                raise CorpusMismatch(
                    f"verdicts carry corpus fingerprint(s) {wrong_corpus} but this run is "
                    f"{self.corpus_fingerprint!r}"
                )

            existing = {
                (v.response_id, v.judge_model_id, v.sample_index) for v in self.load_verdicts()
            }
            incoming: set = set()
            for verdict in verdicts:
                key = (verdict.response_id, verdict.judge_model_id, verdict.sample_index)
                if key in existing or key in incoming:
                    raise StoreError(
                        f"refusing to double-count a vote: {key} is already recorded. "
                        "A repeated (response, judge, sample_index) triple narrows the "
                        "interval on evidence that was only gathered once."
                    )
                incoming.add(key)

        os.makedirs(self.verdicts_dir, exist_ok=True)
        by_judge: Dict[str, List[Verdict]] = {}
        for verdict in verdicts:
            by_judge.setdefault(verdict.judge_model_id, []).append(verdict)

        appended = 0
        for judge_model_id, group in sorted(by_judge.items()):
            appended += _write_jsonl(
                self.verdicts_path(judge_model_id),
                (v.model_dump(mode="json") for v in group),
                mode="a",
            )
        return appended

    def load_verdicts(self, judge_model_id: Optional[str] = None) -> List[Verdict]:
        if not os.path.isdir(self.verdicts_dir):
            return []
        verdicts: List[Verdict] = []
        for filename in sorted(os.listdir(self.verdicts_dir)):
            if not filename.endswith(".jsonl"):
                continue
            if judge_model_id is not None and filename != f"{_safe(judge_model_id)}.jsonl":
                continue
            for row in _read_jsonl(os.path.join(self.verdicts_dir, filename)):
                verdicts.append(Verdict.model_validate(row))
        return verdicts

    def verdicts_by_response(self) -> Dict[str, List[Verdict]]:
        grouped: Dict[str, List[Verdict]] = {}
        for verdict in self.load_verdicts():
            grouped.setdefault(verdict.response_id, []).append(verdict)
        return grouped

    # -- integrity --------------------------------------------------------
    def check_integrity(self) -> Dict[str, object]:
        """Everything that can be checked without re-running anything.

        Returned rather than raised, so a caller can report the state of a run without the check
        itself becoming the failure. ``ok`` is the single field a gate should read.
        """
        manifest = self.load_manifest()
        responses = self.load_responses()
        verdicts = self.load_verdicts()

        known = {r.response_id for r in responses}
        orphans = sorted({v.response_id for v in verdicts if v.response_id not in known})
        wrong_corpus = sorted(
            {v.corpus_fingerprint for v in verdicts
             if v.corpus_fingerprint != self.corpus_fingerprint}
        )

        # k samples per (response, judge) should be distinct indices. Repeats mean a cache key
        # collapsed them, which would report zero variance from what looks like k samples.
        seen: Dict[tuple, int] = {}
        for verdict in verdicts:
            key = (verdict.response_id, verdict.judge_model_id, verdict.sample_index)
            seen[key] = seen.get(key, 0) + 1
        duplicate_samples = sorted(k for k, count in seen.items() if count > 1)

        judged = {v.response_id for v in verdicts}
        unjudged = sorted(known - judged)
        abstentions = sum(len(v.abstained_dimensions) for v in verdicts)

        return {
            "run_id": self.run_id,
            "corpus_fingerprint": self.corpus_fingerprint,
            "manifest_fingerprint": manifest.corpus_fingerprint,
            "n_responses": len(responses),
            "n_verdicts": len(verdicts),
            "pairs": self.pairs(),
            "judges": sorted({v.judge_model_id for v in verdicts}),
            # Not an error: a run mid-judging legitimately has unjudged responses. Reported so a
            # partially complete run cannot be mistaken for a finished one at analysis time.
            "responses_with_no_verdict": len(unjudged),
            "unjudged_examples": unjudged[:5],
            # Recorded before anything downstream can drop them (project rule: abstentions are
            # never imputed and never dropped before the rate is recorded).
            "n_abstained_dimensions": abstentions,
            "repaired_verdicts": sum(1 for v in verdicts if v.repaired),
            "orphan_verdicts": orphans,
            "wrong_corpus_verdicts": wrong_corpus,
            "duplicate_sample_indices": [list(k) for k in duplicate_samples[:10]],
            "ok": not orphans and not wrong_corpus and not duplicate_samples,
        }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def list_fingerprints(runs_dir: str = DEFAULT_RUNS_DIR) -> List[str]:
    if not os.path.isdir(runs_dir):
        return []
    return sorted(
        name for name in os.listdir(runs_dir)
        if os.path.isdir(os.path.join(runs_dir, name))
    )


def list_runs(corpus_fingerprint: str, runs_dir: str = DEFAULT_RUNS_DIR) -> List[str]:
    root = os.path.join(runs_dir, _safe(corpus_fingerprint))
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if os.path.exists(os.path.join(root, name, MANIFEST))
    )
