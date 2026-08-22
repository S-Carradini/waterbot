"""Content-addressed verdict cache (L2).

WHY A CACHE AT ALL
------------------
Grading is 92% of a run's cost. Re-judging the same frozen response under the same
configuration should cost nothing, which is what makes an ablation grid affordable and what
makes a failed run resumable rather than restarted.

THE KEY IS THE WHOLE DESIGN
---------------------------
Every input that could change a verdict is in the key, and one of them matters more than the
rest:

    sha256(judge_model_id, prompt_hash, rubric_hash, corpus_fingerprint,
           item_id, sample_index, temperature, protocol, order)

``sample_index`` **must** be in the key (invariant 4). Leave it out and k=5 collapses to one
cached verdict served five times, which reports perfect agreement and zero variance from a panel
that was only ever asked once. That is the single easiest way to fake an excellent result by
accident, and it would look exactly like the finding this project is trying to establish.

The others each answer a real question. Drop ``corpus_fingerprint`` and a repaired corpus serves
verdicts formed against the corrupted one. Drop ``temperature`` and the T=0 and T=0.3 arms share
entries, destroying the comparison in RQ2. Drop ``order`` and the position-bias swap returns its
own mirror image, making the measured bias exactly zero.

A high hit rate on a fresh configuration is therefore a bug signal, not good news, and
``CacheStats`` exists so a runner can refuse to proceed on one.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterator, Optional

from eval.judge.schemas import Verdict, stable_hash


class CacheError(RuntimeError):
    """Raised when the cache is asked to do something that would corrupt a result."""


def cache_key(
    judge_model_id: str,
    prompt_hash: str,
    rubric_hash: str,
    corpus_fingerprint: str,
    item_id: str,
    sample_index: int,
    temperature: float,
    protocol: str = "pointwise",
    order: str = "none",
) -> str:
    """The content address of one verdict.

    Every argument is required and positional-by-name on purpose. A default for
    ``sample_index`` would let a caller omit the one field whose absence silently destroys the
    variance estimate.
    """
    if sample_index < 0:
        raise CacheError("sample_index must be non-negative")
    if not judge_model_id:
        raise CacheError("judge_model_id is required; an empty id would pool distinct judges")
    return stable_hash(
        {
            "judge_model_id": judge_model_id,
            "prompt_hash": prompt_hash,
            "rubric_hash": rubric_hash,
            "corpus_fingerprint": corpus_fingerprint,
            "item_id": item_id,
            "sample_index": sample_index,
            # Normalised so 0.3 and 0.30 do not become different cache entries.
            "temperature": round(float(temperature), 4),
            "protocol": protocol,
            "order": order,
        },
        length=32,
    )


@dataclass
class CacheStats:
    """Hit accounting, reported so an implausible hit rate is visible before it costs anything."""

    hits: int = 0
    misses: int = 0
    writes: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "lookups": self.lookups,
            "hit_rate": self.hit_rate,
        }


class VerdictCache:
    """A JSONL-backed verdict cache, keyed by content.

    Append-only on disk: a rewrite could lose entries a concurrent run had just written, and the
    file is cheap to compact offline if it ever matters. Loading keeps the last entry for a key,
    so a deliberate re-run appended later wins over the original.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self._entries: Dict[str, Verdict] = {}
        self._lock = threading.Lock()
        self.stats = CacheStats()
        if path and os.path.exists(path):
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        with open(self.path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    self._entries[row["cache_key"]] = Verdict.model_validate(row["verdict"])
                except Exception as exc:  # noqa: BLE001 - any unreadable row names its line
                    # Deliberately broad: a row can fail as bad JSON, as a missing key, or as a
                    # verdict that no longer satisfies its contract after a schema change. All
                    # three mean the same thing to a caller - this cache file cannot be trusted -
                    # and all three need the line number to be fixable.
                    raise CacheError(f"{self.path} line {number} is unreadable: {exc}") from exc

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> Optional[Verdict]:
        with self._lock:
            verdict = self._entries.get(key)
            if verdict is None:
                self.stats.misses += 1
            else:
                self.stats.hits += 1
            return verdict

    def put(self, key: str, verdict: Verdict) -> None:
        """Store a verdict. Storing a different verdict under an existing key is refused.

        If two verdicts collide on a key they disagree about something the key does not capture,
        which means the key is incomplete. Overwriting would hide that; raising surfaces it while
        it is still one run rather than a whole grid.
        """
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and existing != verdict:
                raise CacheError(
                    f"cache key {key[:12]}... already holds a different verdict. Two verdicts "
                    "sharing a key means the key omits something that changed the result."
                )
            self._entries[key] = verdict
            self.stats.writes += 1
            if self.path:
                self._append(key, verdict)

    def _append(self, key: str, verdict: Verdict) -> None:
        assert self.path is not None
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="") as handle:
            handle.write(
                json.dumps(
                    {"cache_key": key, "verdict": verdict.model_dump(mode="json")},
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")

    def keys(self) -> Iterator[str]:
        return iter(sorted(self._entries))

    def reset_stats(self) -> None:
        self.stats = CacheStats()


def implausible_hit_rate(stats: CacheStats, fresh_configuration: bool, threshold: float = 0.1) -> bool:
    """True when a fresh configuration is hitting cache more than it plausibly should.

    A configuration nothing has run before should miss almost everything. Hits mean the key is
    not separating configurations, and the most likely omission is the one that matters most.
    Checked before spending, because the failure is invisible afterwards - the run completes,
    costs less than expected, and reports suspiciously tidy agreement.
    """
    return fresh_configuration and stats.lookups >= 10 and stats.hit_rate > threshold
