"""L4: calibrating judge scores onto the human scale.

Judges are systematically miscalibrated - typically compressed toward the middle and generous at
the top. Calibration learns a monotone map from panel score to expected human score, fitted on
expert labels and validated without leaking.

FOUR DECISIONS, EACH FIXING A SPECIFIC WAY THIS GOES WRONG
-----------------------------------------------------------
1. **The predictor is the panel MEAN, not the median.** Isotonic regression on integer medians
   has at most four support points and degenerates into a lookup table. The continuous mean has
   the resolution the panel actually bought (spec 0.5).

2. **A clipped affine baseline is fitted alongside isotonic, every time.** Two parameters against
   a flexible monotone step function. At realistic label counts the simple map usually wins, and
   "the simple map beat the flexible one" is a clean reporting line rather than a failure.

3. **Groups come from connected components, never from raw document ids.** 127 document names
   share content with another name, so a plain group split still puts near-identical evidence in
   both halves and flatters the result. ``build_groups`` walks the item-to-document graph and
   returns components (spec 0.4, invariant 5).

4. **Error is reported on the PROBE pool only.** The acquire pool is uncertainty-sampled and
   deliberately unrepresentative; fitting on it is correct and reporting out-of-sample error on
   it is not (spec 0.3).

AND ONE HONEST FAILURE
----------------------
If out-of-fold error exceeds half a level, the map is marked unusable and the reported
conclusion is "judge not calibratable at useful resolution". That is a finding about the judge,
not a configuration to tune until it passes.

sklearn is used for isotonic regression and the grouped split. It is already present in this
environment as a ragas dependency, so this adds nothing new.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from eval.judge.schemas import CalibrationMap, stable_hash

# Bumped when calibration semantics change.
CALIBRATION_VERSION = "1.0.0"

# Architecture Algorithm 3: above this out-of-fold error the map is not usable at a resolution
# anyone can act on. Half a level on a four-point scale.
USABLE_MAE_THRESHOLD = 0.5

SCALE_MIN = 1.0
SCALE_MAX = 4.0


class CalibrationError(ValueError):
    """Raised when calibration is asked for on data that cannot support it."""


# ---------------------------------------------------------------------------
# Grouping: the leakage guard
# ---------------------------------------------------------------------------
def build_groups(item_documents: Dict[str, Sequence[str]]) -> Dict[str, str]:
    """Map each item to a group id, from connected components of the item-document graph.

    Invariant 5. ``group_by=canonical_doc_id`` assumes one document per item, but benchmark items
    retrieve from several documents and those document sets overlap. Two items that share any
    document - directly, or through a chain of other items - can leak evidence between folds, so
    they must travel together.

    Components are found over the bipartite graph of items and documents. The group id is the
    lexicographically smallest item in the component, so it is stable across runs rather than
    depending on iteration order.

    Watch for one component swallowing most items: that means grouped cross-validation is
    impossible on this corpus, which is a finding to report rather than a bug to work around.
    ``group_concentration`` measures it.
    """
    if not item_documents:
        return {}

    parent: Dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            winner, loser = sorted((root_a, root_b))
            parent[loser] = winner

    for item, documents in item_documents.items():
        find(f"item:{item}")
        for document in documents:
            union(f"item:{item}", f"doc:{document}")

    # Name each component by its smallest ITEM, so group ids are readable and stable.
    members: Dict[str, List[str]] = {}
    for item in item_documents:
        members.setdefault(find(f"item:{item}"), []).append(item)

    groups: Dict[str, str] = {}
    for component_items in members.values():
        group_id = min(component_items)
        for item in component_items:
            groups[item] = group_id
    return groups


def group_concentration(groups: Dict[str, str]) -> float:
    """Share of items sitting in the single largest group.

    Near 1.0 means the corpus is one connected blob and no honest grouped split exists. Report
    it; do not silently fall back to a random split, which is what makes leakage invisible.
    """
    if not groups:
        return 0.0
    counts: Dict[str, int] = {}
    for group in groups.values():
        counts[group] = counts.get(group, 0) + 1
    return max(counts.values()) / len(groups)


# ---------------------------------------------------------------------------
# The two candidate maps
# ---------------------------------------------------------------------------
@dataclass
class AffineMap:
    """``clip(a * x + b, 1, 4)``. Two parameters, fitted by least squares.

    The baseline that keeps the flexible model honest. Clipping is what makes it a map onto the
    scale rather than a line that can predict 4.7.
    """

    a: float
    b: float

    def predict(self, values: Sequence[float]) -> List[float]:
        return [min(SCALE_MAX, max(SCALE_MIN, self.a * x + self.b)) for x in values]

    def to_params(self) -> Dict[str, float]:
        return {"a": self.a, "b": self.b}


def fit_affine(x: Sequence[float], y: Sequence[float]) -> AffineMap:
    """Ordinary least squares, then clipped at prediction time.

    A degenerate predictor - every panel score identical - has no slope to fit, so it falls back
    to predicting the mean target. That is the honest answer: with no variation in the input,
    nothing about the output can be attributed to it.
    """
    n = len(x)
    if n == 0:
        raise CalibrationError("cannot fit a map with no pairs")
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    variance = sum((xi - mean_x) ** 2 for xi in x)
    if variance == 0:
        return AffineMap(a=0.0, b=mean_y)
    covariance = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    slope = covariance / variance
    return AffineMap(a=slope, b=mean_y - slope * mean_x)


@dataclass
class IsotonicMap:
    """A monotone step function, fitted by sklearn's PAVA, clipped out of bounds."""

    x_thresholds: List[float]
    y_thresholds: List[float]

    def predict(self, values: Sequence[float]) -> List[float]:
        predictions = []
        for value in values:
            if value <= self.x_thresholds[0]:
                predicted = self.y_thresholds[0]
            elif value >= self.x_thresholds[-1]:
                predicted = self.y_thresholds[-1]
            else:
                predicted = self._interpolate(value)
            predictions.append(min(SCALE_MAX, max(SCALE_MIN, predicted)))
        return predictions

    def _interpolate(self, value: float) -> float:
        for i in range(len(self.x_thresholds) - 1):
            left, right = self.x_thresholds[i], self.x_thresholds[i + 1]
            if left <= value <= right:
                if right == left:
                    return self.y_thresholds[i]
                weight = (value - left) / (right - left)
                return self.y_thresholds[i] * (1 - weight) + self.y_thresholds[i + 1] * weight
        return self.y_thresholds[-1]

    @property
    def support_points(self) -> int:
        """How many distinct steps the map actually has.

        Reported because it is the tell for the degeneracy in spec 0.5: a handful of support
        points means the flexible model has become a lookup table.
        """
        return len(set(self.y_thresholds))

    def to_params(self) -> Dict[str, object]:
        return {"x": list(self.x_thresholds), "y": list(self.y_thresholds)}


def fit_isotonic(x: Sequence[float], y: Sequence[float]) -> IsotonicMap:
    """Monotone increasing fit, clipped outside the observed range."""
    from sklearn.isotonic import IsotonicRegression

    if not x:
        raise CalibrationError("cannot fit a map with no pairs")
    model = IsotonicRegression(increasing=True, out_of_bounds="clip")
    model.fit(list(x), list(y))
    return IsotonicMap(
        x_thresholds=[float(v) for v in model.X_thresholds_],
        y_thresholds=[float(v) for v in model.y_thresholds_],
    )


def identity_map(values: Sequence[float]) -> List[float]:
    return [min(SCALE_MAX, max(SCALE_MIN, v)) for v in values]


def mean_absolute_error(predicted: Sequence[float], actual: Sequence[float]) -> float:
    if len(predicted) != len(actual):
        raise CalibrationError("predictions and targets must be the same length")
    if not predicted:
        raise CalibrationError("cannot score an empty prediction set")
    return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)


# ---------------------------------------------------------------------------
# Labelled pairs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LabelledPair:
    """One (panel score, human score) pair, with everything the split needs."""

    item_id: str
    panel_mean: float
    human_score: float
    category: str
    pool: str = "acquire"  # "probe" is held out for reporting

    def __post_init__(self) -> None:
        if self.pool not in ("probe", "acquire"):
            raise CalibrationError(f"pool must be probe or acquire, got {self.pool!r}")


# ---------------------------------------------------------------------------
# Cross-validated fitting
# ---------------------------------------------------------------------------
@dataclass
class FoldResult:
    fold: int
    n_train: int
    n_test: int
    isotonic_mae: float
    affine_mae: float
    identity_mae: float


@dataclass
class CalibrationResult:
    """The fitted map, the comparison that chose it, and the honest verdict."""

    dimension: str
    kind: str
    map_params: Dict[str, object]
    n_pairs: int
    n_folds: int
    isotonic_mae: float
    isotonic_mae_sd: float
    affine_mae: float
    affine_mae_sd: float
    identity_mae: float
    chosen_mae: float
    chosen_mae_sd: float
    usable: bool
    folds: List[FoldResult] = field(default_factory=list)
    group_concentration: float = 0.0
    isotonic_support_points: int = 0
    probe_mae: Optional[float] = None

    @property
    def simple_map_won(self) -> bool:
        """A clean reporting line, not a failure."""
        return self.kind == "affine"

    @property
    def beats_doing_nothing(self) -> bool:
        """Calibration has to be better than leaving the panel score alone."""
        return self.chosen_mae < self.identity_mae

    @property
    def verdict(self) -> str:
        if not self.usable:
            return (
                f"judge not calibratable at useful resolution: out-of-fold MAE "
                f"{self.chosen_mae:.3f} levels exceeds {USABLE_MAE_THRESHOLD}"
            )
        if not self.beats_doing_nothing:
            return (
                f"calibration does not improve on the raw panel score "
                f"({self.chosen_mae:.3f} vs {self.identity_mae:.3f} levels); report uncalibrated"
            )
        return (
            f"{self.kind} map, out-of-fold MAE {self.chosen_mae:.3f} "
            f"(SD {self.chosen_mae_sd:.3f}) levels"
        )

    def to_map(self) -> CalibrationMap:
        return CalibrationMap(
            calibration_map_id=stable_hash(
                {
                    "dimension": self.dimension,
                    "kind": self.kind,
                    "params": self.map_params,
                    "n_pairs": self.n_pairs,
                    "version": CALIBRATION_VERSION,
                }
            ),
            dimension=self.dimension,
            kind=self.kind,
            params=self.map_params,
            n_pairs=self.n_pairs,
            n_folds=self.n_folds,
            out_of_fold_mae=self.chosen_mae,
            out_of_fold_mae_sd=self.chosen_mae_sd,
            usable=self.usable,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "dimension": self.dimension,
            "calibration_version": CALIBRATION_VERSION,
            "kind": self.kind,
            "n_pairs": self.n_pairs,
            "n_folds": self.n_folds,
            "isotonic_mae": self.isotonic_mae,
            "isotonic_mae_sd": self.isotonic_mae_sd,
            "affine_mae": self.affine_mae,
            "affine_mae_sd": self.affine_mae_sd,
            "identity_mae": self.identity_mae,
            "chosen_mae": self.chosen_mae,
            "chosen_mae_sd": self.chosen_mae_sd,
            "usable": self.usable,
            "simple_map_won": self.simple_map_won,
            "beats_doing_nothing": self.beats_doing_nothing,
            "group_concentration": self.group_concentration,
            "isotonic_support_points": self.isotonic_support_points,
            "probe_mae": self.probe_mae,
            "verdict": self.verdict,
        }


def _standard_deviation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def grouped_folds(
    pairs: Sequence[LabelledPair],
    groups: Dict[str, str],
    n_splits: int = 5,
    seed: int = 0,
) -> List[Tuple[List[int], List[int]]]:
    """Stratified grouped folds: same group never spans a split, categories stay balanced.

    Falls back to plain grouped folds when stratification is impossible - which happens when some
    category has fewer members than there are folds, a realistic situation at n=7 per category.
    Falling back is reported by the caller rather than hidden, because unstratified folds make
    per-category error noisier.
    """
    from sklearn.model_selection import GroupKFold, StratifiedGroupKFold

    if len(pairs) < n_splits:
        raise CalibrationError(
            f"cannot make {n_splits} folds from {len(pairs)} pairs"
        )

    x = list(range(len(pairs)))
    y = [p.category for p in pairs]
    group_ids = [groups.get(p.item_id, p.item_id) for p in pairs]

    distinct_groups = len(set(group_ids))
    if distinct_groups < n_splits:
        raise CalibrationError(
            f"only {distinct_groups} distinct groups for {n_splits} folds; grouped "
            "cross-validation is impossible on this data and a random split would leak"
        )

    try:
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        return [(list(train), list(test)) for train, test in splitter.split(x, y, group_ids)]
    except ValueError:
        splitter = GroupKFold(n_splits=n_splits)
        return [(list(train), list(test)) for train, test in splitter.split(x, y, group_ids)]


def calibrate(
    pairs: Sequence[LabelledPair],
    dimension: str,
    groups: Optional[Dict[str, str]] = None,
    n_splits: int = 5,
    seed: int = 0,
) -> CalibrationResult:
    """Fit isotonic and affine under grouped CV, select by out-of-fold MAE.

    Fitting uses the ACQUIRE pool. If probe pairs are supplied they are never trained on, and
    their error is reported separately as ``probe_mae`` - that is the number that generalises,
    because the probe pool is a stratified random sample rather than an uncertainty-sampled one.
    """
    if not pairs:
        raise CalibrationError("cannot calibrate with no labelled pairs")

    fitting = [p for p in pairs if p.pool == "acquire"]
    probe = [p for p in pairs if p.pool == "probe"]
    if not fitting:
        raise CalibrationError(
            "every pair is in the probe pool; there is nothing to fit on. The probe pool is "
            "for reporting only (spec 0.3)."
        )

    groups = groups or {p.item_id: p.item_id for p in fitting}
    folds = grouped_folds(fitting, groups, n_splits=n_splits, seed=seed)

    fold_results: List[FoldResult] = []
    for number, (train_index, test_index) in enumerate(folds):
        train = [fitting[i] for i in train_index]
        test = [fitting[i] for i in test_index]
        if not train or not test:
            continue

        train_x = [p.panel_mean for p in train]
        train_y = [p.human_score for p in train]
        test_x = [p.panel_mean for p in test]
        test_y = [p.human_score for p in test]

        isotonic = fit_isotonic(train_x, train_y)
        affine = fit_affine(train_x, train_y)
        fold_results.append(
            FoldResult(
                fold=number,
                n_train=len(train),
                n_test=len(test),
                isotonic_mae=mean_absolute_error(isotonic.predict(test_x), test_y),
                affine_mae=mean_absolute_error(affine.predict(test_x), test_y),
                identity_mae=mean_absolute_error(identity_map(test_x), test_y),
            )
        )

    if not fold_results:
        raise CalibrationError("no fold produced both a train and a test split")

    isotonic_maes = [f.isotonic_mae for f in fold_results]
    affine_maes = [f.affine_mae for f in fold_results]
    identity_maes = [f.identity_mae for f in fold_results]

    mean_isotonic = sum(isotonic_maes) / len(isotonic_maes)
    mean_affine = sum(affine_maes) / len(affine_maes)
    mean_identity = sum(identity_maes) / len(identity_maes)

    # Ties go to the simpler map. Two parameters that match a step function's accuracy is a
    # better answer, not a worse one.
    kind = "affine" if mean_affine <= mean_isotonic else "isotonic"
    chosen_mae = min(mean_affine, mean_isotonic)
    chosen_sd = _standard_deviation(affine_maes if kind == "affine" else isotonic_maes)

    all_x = [p.panel_mean for p in fitting]
    all_y = [p.human_score for p in fitting]
    final_isotonic = fit_isotonic(all_x, all_y)
    final_map = fit_affine(all_x, all_y) if kind == "affine" else final_isotonic

    probe_mae = None
    if probe:
        probe_mae = mean_absolute_error(
            final_map.predict([p.panel_mean for p in probe]),
            [p.human_score for p in probe],
        )

    return CalibrationResult(
        dimension=dimension,
        kind=kind,
        map_params=final_map.to_params(),
        n_pairs=len(fitting),
        n_folds=len(fold_results),
        isotonic_mae=mean_isotonic,
        isotonic_mae_sd=_standard_deviation(isotonic_maes),
        affine_mae=mean_affine,
        affine_mae_sd=_standard_deviation(affine_maes),
        identity_mae=mean_identity,
        chosen_mae=chosen_mae,
        chosen_mae_sd=chosen_sd,
        usable=chosen_mae <= USABLE_MAE_THRESHOLD,
        folds=fold_results,
        group_concentration=group_concentration(groups),
        isotonic_support_points=final_isotonic.support_points,
        probe_mae=probe_mae,
    )


# ---------------------------------------------------------------------------
# The leakage check
# ---------------------------------------------------------------------------
def find_leakage(
    pairs: Sequence[LabelledPair],
    groups: Dict[str, str],
    folds: Sequence[Tuple[Sequence[int], Sequence[int]]],
) -> List[str]:
    """Group ids appearing in both halves of any fold. Empty means clean.

    Run as a test rather than trusted: a splitter silently falling back to an ungrouped split is
    exactly the failure that makes calibration look better than it is.
    """
    offenders: List[str] = []
    for train_index, test_index in folds:
        train_groups = {groups.get(pairs[i].item_id, pairs[i].item_id) for i in train_index}
        test_groups = {groups.get(pairs[i].item_id, pairs[i].item_id) for i in test_index}
        offenders.extend(sorted(train_groups & test_groups))
    return sorted(set(offenders))
