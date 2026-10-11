"""
Canonical document identity for the evaluation harness.

WHY THIS EXISTS
---------------
Retrieval scoring joins the benchmark's `gold_source_ids` against the
`metadata["name"]` field on retrieved chunks. That join is a raw string
comparison, which silently breaks when the same underlying document has been
ingested into the corpus under more than one filename. WaterBot's corpus has
many such cases, e.g.:

    ADPAR.pdf
    ADPAR_2023_FINAL.pdf
    Arizona Drought Preparedness Report 2023.pdf

Those are one document under three names. When the benchmark names one alias
and retrieval returns another, a correct retrieval is scored as a miss. This
is not hypothetical: it is why the suite reported recall@4 = 0.13 while
keyword_hit_rate (which compares chunk *text*, not filenames) was 0.60 —
a 4.5x gap that can only be explained by a broken identity join.

DESIGN: PROPOSE, DON'T GUESS
----------------------------
Automatically merging documents that "look similar" is dangerous in exactly
the wrong direction: it inflates recall and would hide the very failure this
module exists to expose. Acronym/full-title pairs like the ADPAR group above
cannot be resolved by any string normalization anyway.

So equivalence is *explicit and human-reviewed*, stored in `aliases.yaml`.
This module additionally provides a discovery tool that *proposes* candidate
alias groups by fuzzy similarity for a human to confirm — it never applies
them on its own.

Normalization here only handles unambiguous formatting noise (case,
extension, separators, trailing version/copy markers). It never merges
tokens that differ in meaning.
"""

import difflib
import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

_script_dir = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALIAS_PATH = os.path.join(_script_dir, "aliases.yaml")

# Trailing markers that indicate a copy/version of the same document rather
# than a different document: "(17)", "_0", "-final", "v2", " copy".
_TRAILING_NOISE = re.compile(
    r"(?:"
    r"\(\s*\d+\s*\)"          # (17)
    r"|\bcopy\b"
    r"|\bfinal\b"
    r"|\bv\d+\b"              # v2
    r"|_\d+$"                 # _0
    r")",
    re.IGNORECASE,
)

_KNOWN_EXTENSIONS = (".pdf", ".txt", ".md", ".html", ".htm", ".docx")


def strip_extension(name: str) -> str:
    lowered = name.lower()
    for ext in _KNOWN_EXTENSIONS:
        if lowered.endswith(ext):
            return name[: -len(ext)]
    return name


def normalize_name(name: str) -> str:
    """Normalize away formatting noise only — never meaning.

    'ADPAR_2023_FINAL.pdf' -> 'adpar 2023'
    'Lake havasu City Water Savers.pdf' -> 'lake havasu city water savers'

    Note the second example still differs from 'Lake Havasu Water Savers.pdf'
    by the token 'city'. That is deliberate: deciding those are the same
    document is a human judgement, recorded in aliases.yaml.
    """
    if not name:
        return ""
    text = strip_extension(str(name).strip())
    text = text.replace("_", " ").replace("-", " ")
    text = _TRAILING_NOISE.sub(" ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def basename_of(path_or_name: str) -> str:
    """Corpus metadata sometimes carries a full path in `source`; take the leaf."""
    if not path_or_name:
        return ""
    return re.split(r"[\\/]", str(path_or_name))[-1]


class CanonicalResolver:
    """Resolves any document name to a stable canonical id.

    Resolution order:
      1. Explicit alias group from aliases.yaml (by normalized member name)
      2. Normalized name itself (identity)

    Unknown names resolve to their own normalized form, so a resolver with no
    alias file behaves exactly like the previous raw-string matching, minus
    formatting noise. Adding aliases can only merge, never split.
    """

    def __init__(self, alias_groups: Optional[List[dict]] = None):
        self._alias_groups = alias_groups or []
        self._member_to_canonical: Dict[str, str] = {}
        self._canonical_to_members: Dict[str, List[str]] = {}
        self._unverified: List[str] = []

        for group in self._alias_groups:
            canonical = group.get("canonical_id")
            members = group.get("members") or []
            if not canonical or not members:
                continue
            canonical_key = normalize_name(canonical) or canonical
            self._canonical_to_members[canonical_key] = list(members)
            if not group.get("verified", False):
                self._unverified.append(canonical)
            for member in members:
                self._member_to_canonical[normalize_name(member)] = canonical_key
            # The canonical name itself is always a member of its own group.
            self._member_to_canonical[canonical_key] = canonical_key

    @property
    def unverified_groups(self) -> List[str]:
        """Alias groups not yet confirmed by a human. Surfaced by preflight."""
        return list(self._unverified)

    @property
    def group_count(self) -> int:
        return len(self._canonical_to_members)

    def resolve(self, name: str) -> str:
        """Map a raw filename (or path) to its canonical id."""
        normalized = normalize_name(basename_of(name))
        return self._member_to_canonical.get(normalized, normalized)

    def resolve_all(self, names: Iterable[str]) -> List[str]:
        """Resolve a sequence, preserving order and duplicates.

        Order and multiplicity matter: MRR and NDCG depend on rank position,
        so this must not deduplicate.
        """
        return [self.resolve(n) for n in names]

    def members_of(self, canonical_id: str) -> List[str]:
        return self._canonical_to_members.get(canonical_id, [])


def load_alias_groups(path: str = DEFAULT_ALIAS_PATH) -> List[dict]:
    """Load alias groups from YAML. Missing file is not an error."""
    if not os.path.exists(path):
        return []
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required to read aliases.yaml. "
            "Install with: pip install -r eval/requirements-eval.txt"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("alias_groups", []) or []


def build_resolver(path: str = DEFAULT_ALIAS_PATH) -> CanonicalResolver:
    return CanonicalResolver(load_alias_groups(path))


# ---------------------------------------------------------------------------
# Discovery: propose candidate alias groups for human review.
# This never mutates aliases.yaml — it only reports.
# ---------------------------------------------------------------------------

# Tokens too common in this corpus to carry identity signal on their own.
_LOW_SIGNAL_TOKENS = {
    "arizona", "az", "water", "the", "of", "for", "and", "a", "an", "in",
    "to", "on", "report", "fact", "sheet", "plan", "study", "final", "draft",
    "2020", "2021", "2022", "2023", "2024", "2025",
}


def _signal_tokens(normalized: str) -> Set[str]:
    return {t for t in normalized.split() if t and t not in _LOW_SIGNAL_TOKENS}


def similarity(a: str, b: str) -> float:
    """Blend sequence ratio with signal-token Jaccard.

    Sequence ratio catches near-identical strings; token Jaccard catches
    reordering and insertions. Both are needed: 'Lake Havasu Water Savers'
    vs 'Lake havasu City Water Savers' scores high on both, while
    'ADPAR' vs 'Arizona Drought Preparedness Report 2023' scores low on
    both and correctly requires a human to link them.
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    ratio = difflib.SequenceMatcher(None, na, nb).ratio()

    ta, tb = _signal_tokens(na), _signal_tokens(nb)
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
    else:
        jaccard = 0.0

    return max(ratio, (ratio + jaccard) / 2)


_NUMERIC_TOKEN = re.compile(r"^\d+$")


def classify_pair(a: str, b: str) -> str:
    """Classify a similar-looking pair of names.

    Returns one of:
      'alias_confident' — one name's tokens are a subset of the other's, so
                          they differ only by formatting/version noise
                          ('ADPAR' vs 'ADPAR 2023 FINAL'). Safe to cluster.
      'distinct_series' — both names carry differing tokens AND at least one
                          side differs numerically, i.e. a numbered/dated
                          series ('2018 Legislative Summary' vs '2019 ...',
                          'Ch. 5.1 Ute' vs 'Ch. 5.2 SUIT'). Never cluster.
      'needs_review'    — both sides differ non-numerically. Could be a real
                          alias ('CAP Colorado River Shortage FAQs' vs
                          'Colorado River Shortage FAQ') or genuinely
                          different documents ('... Cochise County' vs
                          '... Maricopa County'). A human decides.

    This distinction is the whole safety property of this module. Treating a
    numbered series as aliases would silently inflate recall — the same class
    of measurement bug this module exists to eliminate, but in the direction
    that flatters the system instead of penalising it.
    """
    na, nb = normalize_name(a), normalize_name(b)
    ta, tb = set(na.split()), set(nb.split())
    only_a, only_b = ta - tb, tb - ta

    if not only_a or not only_b:
        return "alias_confident"

    if any(_NUMERIC_TOKEN.match(t) for t in only_a | only_b):
        return "distinct_series"

    return "needs_review"


def propose_alias_groups(
    names: Iterable[str],
    threshold: float = 0.80,
    known: Optional[CanonicalResolver] = None,
) -> Dict[str, list]:
    """Discover candidate aliases. Reports; never mutates aliases.yaml.

    Returns:
      {
        "confident_groups": [[name, ...], ...]   # subset-token clusters
        "review_pairs":     [(a, b, score), ...] # human judgement required
        "series_families":  [[name, ...], ...]   # numbered series — NOT aliases
      }

    Only 'alias_confident' pairs are clustered transitively. Allowing
    'needs_review' pairs to union would chain unrelated documents into one
    blob (all eight Legislative Session Summaries collapsing into a single
    "document"), which is precisely the failure mode being guarded against.
    """
    unique = sorted({basename_of(n) for n in names if n})
    parent: Dict[str, str] = {n: n for n in unique}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    review_pairs: List[Tuple[str, str, float]] = []
    series_pairs: List[Tuple[str, str]] = []

    for i, a in enumerate(unique):
        for b in unique[i + 1:]:
            if known is not None and known.resolve(a) == known.resolve(b):
                continue  # already an explicit alias — nothing to propose
            score = similarity(a, b)
            if score < threshold:
                continue
            verdict = classify_pair(a, b)
            if verdict == "alias_confident":
                union(a, b)
            elif verdict == "needs_review":
                review_pairs.append((a, b, round(score, 3)))
            else:
                series_pairs.append((a, b))

    clusters: Dict[str, List[str]] = {}
    for n in unique:
        clusters.setdefault(find(n), []).append(n)
    confident_groups = [sorted(m) for m in clusters.values() if len(m) > 1]

    # Group series pairs into families purely for readable reporting.
    series_parent: Dict[str, str] = {}

    def sfind(x: str) -> str:
        series_parent.setdefault(x, x)
        while series_parent[x] != x:
            series_parent[x] = series_parent[series_parent[x]]
            x = series_parent[x]
        return x

    for a, b in series_pairs:
        # Skip pairs already merged as confident aliases, so a name never
        # appears in both the "alias" and "series" sections of the report.
        if find(a) == find(b):
            continue
        ra, rb = sfind(a), sfind(b)
        if ra != rb:
            series_parent[rb] = ra

    series_clusters: Dict[str, List[str]] = {}
    for n in series_parent:
        series_clusters.setdefault(sfind(n), []).append(n)

    return {
        "confident_groups": sorted(confident_groups),
        "review_pairs": sorted(review_pairs, key=lambda p: -p[2]),
        "series_families": sorted(
            [sorted(m) for m in series_clusters.values() if len(m) > 1]
        ),
    }
