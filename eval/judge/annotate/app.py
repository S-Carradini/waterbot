"""L4: the annotation interface.

    streamlit run eval/judge/annotate/app.py -- \
        --run eval/results/runs/<fingerprint>/<run_id> \
        --annotator ab \
        --labels eval/results/labels/<run_id>.jsonl

One item per screen, rubric anchors always visible, autosave on every score.

WHAT AN ANNOTATOR MUST NOT SEE
------------------------------
System identity, persona, and every judge verdict. Not hidden behind a toggle - not loaded into
the page at all, so there is nothing to reveal by accident and nothing to leak through a
screenshot. If an annotator knows an answer came from WaterBot, or that three judges scored it 4,
the label stops being independent evidence and the human ceiling stops meaning anything.

The check is in the code below, not in a screenshot: ``_scrub`` builds the display record and is
the only thing the page renders.

DELIBERATELY THIN
-----------------
Every rule that matters lives in pools.py and store.py, which are tested without launching a UI.
This file arranges widgets. A bug here shows up as a bad screen; a bug there shows up as a wrong
number in the paper.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from eval.judge.annotate.store import LabelStore  # noqa: E402
from eval.judge.rubric import load_rubric  # noqa: E402
from eval.judge.schemas import HumanLabel, Response  # noqa: E402
from eval.judge.store import ResponseStore  # noqa: E402

SCORE_HELP = "1 = worst, 4 = best. Choose 'insufficient evidence' rather than guessing."


def scrub(response: Response) -> Dict[str, object]:
    """The only view of a response an annotator gets.

    Everything identifying the system, the persona or any judge is dropped here rather than
    hidden in the template. Tested directly, because "the UI does not show it" is not a
    guarantee anyone can check six months later.
    """
    return {
        "item_id": response.item_id,
        "question": response.question,
        "category": response.category,
        "answer": response.answer,
        "passages": [
            {
                "evidence_id": passage.evidence_id,
                "document": passage.canonical_doc_id,
                "text": passage.text,
            }
            for passage in sorted(response.passages, key=lambda p: p.evidence_id)
        ],
        "citations": list(response.citations),
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score frozen responses against the rubric.")
    parser.add_argument("--fingerprint", required=True, help="corpus fingerprint of the run")
    parser.add_argument("--run", required=True, help="run id to annotate")
    parser.add_argument("--annotator", required=True, help="your initials or role, not your name")
    parser.add_argument("--labels", required=True, help="JSONL file to append labels to")
    parser.add_argument("--pool", default="probe", choices=["probe", "acquire"])
    parser.add_argument("--runs-dir", default=None)
    parser.add_argument("--dimensions", default=None, help="comma-separated; default is the rubric's")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:  # pragma: no cover - UI shell
    import streamlit as st

    args = parse_args(argv if argv is not None else sys.argv[1:])

    st.set_page_config(page_title="WaterBot annotation", layout="wide")

    store_kwargs = {"runs_dir": args.runs_dir} if args.runs_dir else {}
    response_store = ResponseStore(args.fingerprint, args.run, **store_kwargs)
    responses = response_store.load_responses()
    rubric = load_rubric()
    labels = LabelStore(args.labels)

    if "index" not in st.session_state:
        st.session_state.index = 0

    total = len(responses)
    if total == 0:
        st.error("This run holds no frozen responses.")
        return

    index = min(st.session_state.index, total - 1)
    response = responses[index]
    view = scrub(response)

    names = (
        [d.strip() for d in args.dimensions.split(",")]
        if args.dimensions
        else rubric.applicable_names(
            view["category"], has_citations=bool(view["citations"])
        )
    )

    # -- header ----------------------------------------------------------
    st.progress((index + 1) / total, text=f"Item {index + 1} of {total}")
    st.caption(
        f"annotator **{args.annotator}** · category **{view['category']}** · "
        f"item **{view['item_id']}**"
    )

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Question")
        st.write(view["question"])

        st.subheader("Answer")
        st.info(view["answer"])

        if view["citations"]:
            st.caption("Citations shown to the reader: " + ", ".join(view["citations"]))
        else:
            st.caption("The answer displayed no citations.")

        st.subheader("Evidence")
        if not view["passages"]:
            st.caption("No passages were retrieved for this question.")
        for passage in view["passages"]:
            with st.expander(f"[{passage['evidence_id']}] {passage['document']}", expanded=True):
                st.write(passage["text"])

    with right:
        st.subheader("Score")
        scores: Dict[str, Optional[int]] = {}
        notes: Dict[str, str] = {}

        for name in names:
            dimension = rubric.get(name)
            st.markdown(f"**{name}**")
            st.caption(dimension.question)
            with st.expander("anchors", expanded=False):
                for level in (4, 3, 2, 1):
                    st.markdown(f"**{level}** — {dimension.anchor(level)}")

            abstain = st.checkbox(
                "insufficient evidence to judge", key=f"abstain_{index}_{name}"
            )
            if abstain:
                scores[name] = None
            else:
                scores[name] = st.radio(
                    "score",
                    [1, 2, 3, 4],
                    index=2,
                    horizontal=True,
                    key=f"score_{index}_{name}",
                    help=SCORE_HELP,
                    label_visibility="collapsed",
                )
            notes[name] = st.text_input("note (optional)", key=f"note_{index}_{name}")
            st.divider()

        if st.button("Save and continue", type="primary", use_container_width=True):
            labels.append(
                [
                    HumanLabel(
                        response_id=response.response_id,
                        dimension=name,
                        annotator_id=args.annotator,
                        score=scores[name],
                        insufficient_evidence=scores[name] is None,
                        pool=args.pool,
                        notes=notes.get(name, ""),
                    )
                    for name in names
                ]
            )
            st.session_state.index = min(index + 1, total - 1)
            st.rerun()

        columns = st.columns(2)
        if columns[0].button("Previous", use_container_width=True, disabled=index == 0):
            st.session_state.index = max(0, index - 1)
            st.rerun()
        if columns[1].button("Skip", use_container_width=True):
            st.session_state.index = min(index + 1, total - 1)
            st.rerun()

        progress = labels.progress(total * len(names))
        st.caption(f"{progress['completed']} labels saved this round")


if __name__ == "__main__":  # pragma: no cover
    main()
