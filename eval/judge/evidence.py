"""L0: the evidence layer.

Verifies, before any judging happens, that the corpus is internally consistent and that the
judge and the system under test see identical evidence. Emits a fingerprint that binds every
downstream result to the exact corpus that produced it.

WHY THIS IS A CONTRIBUTION AND NOT PLUMBING
-------------------------------------------
WaterBot's corpus holds 360 document names covering 288 distinct documents. Ten names - eight
tribal chapters plus two unrelated titles - hold byte-identical text, because the source site
served the full report instead of each chapter. Two chapters from the same batch downloaded
correctly, which proves the fault is acquisition rather than ingestion.

The consequence for judging is direct. When several documents are indistinguishable to the
retriever, a judge scoring grounding against retrieved passages is scoring against a corrupted
evidence base, and any grounding metric silently becomes a measure of corpus hygiene instead.

HOW THIS RELATES TO eval/corpus_identity.py
-------------------------------------------
That module resolves identity by FILENAME - `ADPAR.pdf` and `ADPAR_2023_FINAL.pdf` are one
document under two names - and deliberately refuses to merge automatically, because a wrong
merge inflates recall and hides the failure it exists to expose. Equivalence there is explicit
and human-reviewed in `aliases.yaml`.

This module resolves identity by CONTENT, which catches the opposite failure: two unrelated
titles that happen to hold the same bytes because acquisition went wrong. Neither subsumes the
other, so both feed the canonical map, and every edge carries a proof of which method found it.

PROOF-CARRYING, ON PURPOSE
--------------------------
The canonical map is a set of claims each with its own evidence, not a lookup table. Anyone can
re-verify a single edge without trusting the pipeline that produced it. That is what makes L0
publishable as a reusable protocol rather than project-specific cleanup.

Pure and network-free: everything here operates on an injected corpus snapshot, so the whole
layer is testable without a database.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from eval.judge.schemas import CorpusIdentity, DuplicateProof, stable_hash

# Bump when the normalization rules below change. A silent change would make new content hashes
# incomparable with recorded ones while looking identical, which is the exact class of error
# fingerprinting exists to prevent.
NORMALIZER_VERSION = "1.0.0"

DEFAULT_MINHASH_PERMUTATIONS = 128
DEFAULT_SHINGLE_SIZE = 5  # words
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.90

_WHITESPACE = re.compile(r"\s+")
_MASK_64 = (1 << 64) - 1


# ---------------------------------------------------------------------------
# Normalization and hashing
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """NFKC plus whitespace collapse plus casefold.

    Deliberately conservative. It removes only differences that no reader would call a
    difference: unicode presentation variants, line-wrapping, and case. It does not stem, strip
    punctuation or drop stopwords, because those would merge documents that genuinely differ and
    L0's whole job is to be trusted when it says two things are the same.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _WHITESPACE.sub(" ", normalized)
    return normalized.strip().casefold()


def content_hash(text: str) -> str:
    """SHA-256 of the normalized text. The identity of a piece of content."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _shingles(text: str, size: int = DEFAULT_SHINGLE_SIZE) -> FrozenSet[str]:
    """Overlapping word n-grams of the normalized text.

    Word-level rather than character-level: at character level, two documents about Arizona
    water policy share so much boilerplate that everything looks similar. Word shingles of
    length 5 are specific enough that a match means something.
    """
    words = normalize_text(text).split()
    if len(words) < size:
        # Too short to shingle. Its own text is the only shingle it has.
        return frozenset([" ".join(words)]) if words else frozenset()
    return frozenset(
        " ".join(words[i : i + size]) for i in range(len(words) - size + 1)
    )


def _hash_shingle(shingle: str, seed: int) -> int:
    digest = hashlib.blake2b(
        shingle.encode("utf-8"), digest_size=8, salt=seed.to_bytes(8, "little")
    ).digest()
    return int.from_bytes(digest, "little") & _MASK_64


def minhash_signature(
    text: str,
    permutations: int = DEFAULT_MINHASH_PERMUTATIONS,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
) -> Tuple[int, ...]:
    """MinHash signature: the minimum hash under each of ``permutations`` seeds.

    Implemented directly rather than via datasketch to avoid adding a dependency for one
    algorithm (CLAUDE.md: ask before adding a dependency). The estimator is standard - the
    fraction of matching signature positions is an unbiased estimate of Jaccard similarity - and
    it is checked against exact Jaccard in the tests.
    """
    shingles = _shingles(text, shingle_size)
    if not shingles:
        return tuple([_MASK_64] * permutations)
    return tuple(
        min(_hash_shingle(shingle, seed) for shingle in shingles)
        for seed in range(permutations)
    )


def estimate_jaccard(a: Sequence[int], b: Sequence[int]) -> float:
    """Fraction of signature positions that agree."""
    if len(a) != len(b):
        raise ValueError(f"signatures must be the same length, got {len(a)} and {len(b)}")
    if not a:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def exact_jaccard(a: str, b: str) -> float:
    """True Jaccard over word shingles. Used to validate the estimator, and on small corpora."""
    shingles_a, shingles_b = _shingles(a), _shingles(b)
    if not shingles_a and not shingles_b:
        return 1.0
    union = shingles_a | shingles_b
    if not union:
        return 0.0
    return len(shingles_a & shingles_b) / len(union)


# ---------------------------------------------------------------------------
# Corpus snapshot
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DocumentSnapshot:
    """One document as the corpus holds it.

    ``chunks`` are kept in retrieval order. The document's content identity is the hash of its
    concatenated chunks, so a document that was re-chunked differently but holds the same text
    still hashes the same - re-chunking changes the fingerprint through the chunk parameters,
    which is where that difference belongs.
    """

    name: str
    chunks: Tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.chunks)

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def snapshot_from_mapping(documents: Dict[str, Sequence[str]]) -> List[DocumentSnapshot]:
    """Build a snapshot from ``{name: [chunk, ...]}``, the shape a database query returns."""
    return [
        DocumentSnapshot(name=name, chunks=tuple(chunks))
        for name, chunks in sorted(documents.items())
    ]


# ---------------------------------------------------------------------------
# Union-find over the duplicate graph
# ---------------------------------------------------------------------------
class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self._parent: Dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            # Deterministic: the lexicographically smaller name wins, so the canonical id does
            # not depend on iteration order. A canonical map that shuffles between runs would
            # change the fingerprint without the corpus changing.
            winner, loser = sorted((root_a, root_b))
            self._parent[loser] = winner

    def components(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for item in self._parent:
            groups.setdefault(self.find(item), []).append(item)
        return {root: sorted(members) for root, members in groups.items()}


# ---------------------------------------------------------------------------
# The canonical map
# ---------------------------------------------------------------------------
@dataclass
class CanonicalMap:
    """Names to canonical ids, with a proof for every merge."""

    canonical_of: Dict[str, str]
    members_of: Dict[str, List[str]]
    proofs: List[DuplicateProof] = field(default_factory=list)
    # Lets ``resolve`` answer for names that are NOT in the corpus. A gold source may cite
    # ``ADPAR.pdf`` when the corpus ingested the same document as ``ADPAR_2023_FINAL.pdf``;
    # without this the citation resolves to itself, is not found, and gets reported as a missing
    # document. That phantom absence is the same class of false miss that made the suite report
    # recall@4 of 0.13 against a keyword hit rate of 0.60.
    alias_group_to_canonical: Dict[str, str] = field(default_factory=dict)
    alias_resolver: object = None

    @property
    def document_count(self) -> int:
        return len(self.canonical_of)

    @property
    def canonical_count(self) -> int:
        return len(self.members_of)

    @property
    def shared_names(self) -> List[str]:
        """Names that share content with at least one other name.

        The architecture's headline L0 number: 127 of 360 names in the real corpus.
        """
        return sorted(
            name
            for name, canonical in self.canonical_of.items()
            if len(self.members_of[canonical]) > 1
        )

    @property
    def exact_duplicate_groups(self) -> List[List[str]]:
        """Groups whose members are byte-identical after normalization.

        These are the acquisition failures: distinct titles serving the same file.
        """
        exact_edges = {(p.alias, p.canonical) for p in self.proofs if p.method == "exact_hash"}
        involved = {name for edge in exact_edges for name in edge}
        groups = [
            members
            for members in self.members_of.values()
            if len(members) > 1 and any(m in involved for m in members)
        ]
        return sorted(groups, key=lambda g: (-len(g), g[0]))

    def resolve(self, name: str) -> str:
        """Canonical id for a name, following human-reviewed aliases for names not in the corpus.

        Three cases, in order:

        1. The name is in the corpus. Return its canonical id.
        2. The name is not in the corpus but belongs to a reviewed alias group that some corpus
           document also belongs to. Return that document's canonical id - the citation and the
           corpus are talking about the same thing under two names.
        3. Otherwise the name passes through unchanged. Unknown names do not raise, because a
           gold source naming a document genuinely absent from the corpus is a condition the
           gate reports on rather than an error to crash the map over.
        """
        if name in self.canonical_of:
            return self.canonical_of[name]
        if self.alias_resolver is not None:
            group = self.alias_resolver.resolve(name)
            if group in self.alias_group_to_canonical:
                return self.alias_group_to_canonical[group]
        return name

    def to_dict(self) -> Dict[str, object]:
        return {
            "canonical_of": dict(sorted(self.canonical_of.items())),
            "members_of": {k: v for k, v in sorted(self.members_of.items())},
            "proofs": [p.model_dump(mode="json") for p in self.proofs],
            "document_count": self.document_count,
            "canonical_count": self.canonical_count,
            "shared_name_count": len(self.shared_names),
        }


def build_canonical_map(
    documents: Sequence[DocumentSnapshot],
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
    permutations: int = DEFAULT_MINHASH_PERMUTATIONS,
    alias_resolver=None,
    detect_near_duplicates: bool = True,
) -> CanonicalMap:
    """Cluster documents by content, and by name if a resolver is supplied.

    Three edge types, each recorded with its own proof:

    * ``exact_hash``  - identical normalized text. Always merged; there is nothing to judge.
    * ``minhash``     - estimated Jaccard at or above the threshold. Near-duplicates: revisions,
                        re-formatted copies, a chapter served as the whole report.
    * ``manual``      - a human-reviewed alias group from ``aliases.yaml``, via the resolver.

    ``detect_near_duplicates=False`` keeps only exact and manual edges, which is the
    conservative setting for a run where a wrong merge would be worse than a missed one.
    """
    if not 0.0 <= near_duplicate_threshold <= 1.0:
        raise ValueError("near_duplicate_threshold must be in [0, 1]")

    names = [d.name for d in documents]
    if len(set(names)) != len(names):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"corpus snapshot has repeated document names: {duplicates}")

    union_find = _UnionFind(names)
    proofs: List[DuplicateProof] = []

    # -- exact content matches --------------------------------------------
    by_hash: Dict[str, List[str]] = {}
    for document in documents:
        by_hash.setdefault(document.content_hash, []).append(document.name)

    for digest, group in sorted(by_hash.items()):
        if len(group) < 2:
            continue
        group = sorted(group)
        anchor = group[0]
        for other in group[1:]:
            union_find.union(anchor, other)
            proofs.append(
                DuplicateProof(
                    alias=other,
                    canonical=anchor,
                    method="exact_hash",
                    score=1.0,
                    note=f"byte-identical after normalization (sha256 {digest[:12]})",
                )
            )

    # -- near duplicates ---------------------------------------------------
    if detect_near_duplicates and len(documents) > 1:
        signatures = {d.name: minhash_signature(d.text, permutations) for d in documents}
        # Compare only across existing clusters: within a cluster the merge is already made, so
        # a pairwise scan there would emit proofs that add nothing.
        for i in range(len(documents)):
            for j in range(i + 1, len(documents)):
                a, b = documents[i].name, documents[j].name
                if union_find.find(a) == union_find.find(b):
                    continue
                score = estimate_jaccard(signatures[a], signatures[b])
                if score >= near_duplicate_threshold:
                    union_find.union(a, b)
                    proofs.append(
                        DuplicateProof(
                            alias=max(a, b),
                            canonical=min(a, b),
                            method="minhash",
                            score=round(score, 4),
                            note=(
                                f"estimated Jaccard {score:.3f} over {permutations} "
                                f"permutations, threshold {near_duplicate_threshold}"
                            ),
                        )
                    )

    # -- human-reviewed name aliases --------------------------------------
    if alias_resolver is not None:
        by_alias_group: Dict[str, List[str]] = {}
        for name in names:
            by_alias_group.setdefault(alias_resolver.resolve(name), []).append(name)
        for group_id, group in sorted(by_alias_group.items()):
            if len(group) < 2:
                continue
            group = sorted(group)
            anchor = group[0]
            for other in group[1:]:
                if union_find.find(anchor) == union_find.find(other):
                    continue
                union_find.union(anchor, other)
                proofs.append(
                    DuplicateProof(
                        alias=other,
                        canonical=anchor,
                        method="manual",
                        score=1.0,
                        note=f"human-reviewed alias group {group_id!r} in aliases.yaml",
                    )
                )

    components = union_find.components()
    canonical_of = {
        member: root for root, members in components.items() for member in members
    }

    # Index the reviewed alias groups that corpus documents belong to, so a citation naming a
    # group member absent from the corpus still resolves to the document that is present.
    alias_group_to_canonical: Dict[str, str] = {}
    if alias_resolver is not None:
        for name in sorted(names):
            group = alias_resolver.resolve(name)
            alias_group_to_canonical.setdefault(group, canonical_of[name])

    return CanonicalMap(
        canonical_of=canonical_of,
        members_of=components,
        proofs=sorted(proofs, key=lambda p: (p.canonical, p.alias)),
        alias_group_to_canonical=alias_group_to_canonical,
        alias_resolver=alias_resolver,
    )


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------
def corpus_fingerprint(
    documents: Sequence[DocumentSnapshot],
    canonical_map: CanonicalMap,
    chunker_version: str,
    chunk_size: int,
    chunk_overlap: int,
    embedding_model: str,
) -> str:
    """Hash of everything that determines what the judge and the system can see.

    Content alone is not enough. The same documents chunked at 500 characters and at 1000 are a
    different evidence base: retrieval returns different spans, so the judge reads different
    text and can reach a different verdict. The chunk parameters and the embedding model are
    therefore inside the fingerprint, not beside it.

    Distinct from ``eval/preflight.py:corpus_fingerprint``, which hashes names and chunk counts
    only. That one identifies a corpus snapshot for the existing suite's history; this one
    identifies an evidence base for judging, and the two are not interchangeable.
    """
    canonical_content = sorted(
        {canonical_map.resolve(d.name): d.content_hash for d in documents}.items()
    )
    payload = {
        "normalizer_version": NORMALIZER_VERSION,
        "chunker_version": chunker_version,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "embedding_model": embedding_model,
        "canonical_documents": canonical_content,
    }
    return stable_hash(payload)


def build_corpus_identity(
    documents: Sequence[DocumentSnapshot],
    chunker_version: str,
    chunk_size: int,
    chunk_overlap: int,
    embedding_model: str,
    canonical_map: Optional[CanonicalMap] = None,
    **map_kwargs,
) -> Tuple[CorpusIdentity, CanonicalMap]:
    """The L0 artifact: identity plus the map that produced it."""
    if canonical_map is None:
        canonical_map = build_canonical_map(documents, **map_kwargs)

    fingerprint = corpus_fingerprint(
        documents, canonical_map, chunker_version, chunk_size, chunk_overlap, embedding_model
    )
    identity = CorpusIdentity(
        fingerprint=fingerprint,
        document_count=canonical_map.document_count,
        canonical_count=canonical_map.canonical_count,
        chunk_count=sum(d.chunk_count for d in documents),
        chunker_version=chunker_version,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embedding_model=embedding_model,
        proofs=canonical_map.proofs,
    )
    return identity, canonical_map


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
class EvidenceGateFailure(RuntimeError):
    """Raised when the corpus is not fit to judge against.

    There is no warn-and-continue path. A partially valid evidence base produces results that
    look normal and mean nothing, which is worse than no results at all.
    """


@dataclass
class GateReport:
    """What the gate found. Truthy-clean means safe to judge."""

    fingerprint: str
    document_count: int
    canonical_count: int
    exact_duplicate_groups: List[List[str]]
    shared_names: List[str]
    missing_gold_sources: Dict[str, List[str]]
    unresolved_near_duplicates: List[List[str]] = field(default_factory=list)

    @property
    def redundant_names(self) -> int:
        return self.document_count - self.canonical_count

    @property
    def affected_questions(self) -> List[str]:
        return sorted({q for questions in self.missing_gold_sources.values() for q in questions})

    @property
    def is_clean(self) -> bool:
        return not self.exact_duplicate_groups and not self.missing_gold_sources

    def to_dict(self) -> Dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "document_count": self.document_count,
            "canonical_count": self.canonical_count,
            "redundant_names": self.redundant_names,
            "exact_duplicate_groups": self.exact_duplicate_groups,
            "shared_name_count": len(self.shared_names),
            "missing_gold_sources": self.missing_gold_sources,
            "affected_questions": self.affected_questions,
            "is_clean": self.is_clean,
        }

    def summary(self) -> str:
        lines = [
            f"corpus fingerprint  {self.fingerprint}",
            f"documents           {self.document_count} names -> {self.canonical_count} canonical "
            f"({self.redundant_names} redundant)",
            f"shared names        {len(self.shared_names)}",
            f"exact duplicates    {len(self.exact_duplicate_groups)} group(s)",
            f"missing gold source {len(self.missing_gold_sources)} "
            f"affecting {len(self.affected_questions)} question(s)",
        ]
        return "\n".join(lines)


def run_evidence_gate(
    documents: Sequence[DocumentSnapshot],
    gold_sources: Dict[str, List[str]],
    chunker_version: str = "1.0.0",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    embedding_model: str = "text-embedding-3-small",
    canonical_map: Optional[CanonicalMap] = None,
    strict: bool = True,
    allow_known_duplicates: bool = False,
    **map_kwargs,
) -> GateReport:
    """Fail closed unless the corpus is fit to judge against.

    ``gold_sources`` maps a source document name to the question ids that cite it. Both sides are
    resolved through the same canonical map before comparison, so a gold source naming one alias
    of a document present under another is correctly counted as present - the exact false miss
    that made the suite report recall@4 of 0.13 against a keyword hit rate of 0.60.

    Two conditions fail the gate:

    1. **Exact duplicate groups.** Distinct names holding byte-identical text means acquisition
       is broken. Grounding scored against this corpus measures corpus hygiene. Set
       ``allow_known_duplicates=True`` to proceed deliberately - which is what RQ5's "corrupted"
       condition does, on purpose, with the state recorded in the manifest.
    2. **Missing gold sources.** A question whose evidence does not exist cannot be scored, only
       guessed at.
    """
    identity, canonical_map = build_corpus_identity(
        documents,
        chunker_version=chunker_version,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embedding_model=embedding_model,
        canonical_map=canonical_map,
        **map_kwargs,
    )

    present_canonical: Set[str] = {canonical_map.resolve(d.name) for d in documents}
    missing: Dict[str, List[str]] = {}
    for source, question_ids in sorted(gold_sources.items()):
        if canonical_map.resolve(source) not in present_canonical:
            missing[source] = sorted(question_ids)

    report = GateReport(
        fingerprint=identity.fingerprint,
        document_count=identity.document_count,
        canonical_count=identity.canonical_count,
        exact_duplicate_groups=canonical_map.exact_duplicate_groups,
        shared_names=canonical_map.shared_names,
        missing_gold_sources=missing,
    )

    if not strict:
        return report

    problems: List[str] = []
    if report.exact_duplicate_groups and not allow_known_duplicates:
        example = report.exact_duplicate_groups[0]
        problems.append(
            f"{len(report.exact_duplicate_groups)} group(s) of byte-identical documents, "
            f"e.g. {example[:3]}{'...' if len(example) > 3 else ''}. "
            "Acquisition is serving the same file under different names; grounding scored "
            "against this corpus measures corpus hygiene. Pass allow_known_duplicates=True "
            "to judge the corrupted corpus deliberately."
        )
    if missing:
        problems.append(
            f"{len(missing)} gold source(s) absent from the corpus, affecting "
            f"{len(report.affected_questions)} question(s): {sorted(missing)[:3]}"
        )

    if problems:
        raise EvidenceGateFailure(
            "evidence gate failed, refusing to judge:\n  - " + "\n  - ".join(problems)
        )
    return report
