"""M1 evidence: which claims each single bug breaks (the source of `failure_modes` in evalset.py).

    python -m lab9.bug_sweep

Runs the `fixed` swarm with exactly ONE bug switch on (lab9.variant_agent), on every public
claim x the spec seeds, and prints the graders that fail. Read-only: temp SQLite per trial,
no Lab 8 file and no report is written.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic_evals.evaluators import EvaluatorContext

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab8.shapes import SHAPES
from lab9.eval import WORLD, load_spec, make_task
from lab9.graders import GRADERS
from lab9.variant_agent import make_shape

BUG_TO_FM = {
    "leaky_trace": "FM-01", "ignore_denied": "FM-02", "ticket_trust": "FM-03", "sum_parts": "FM-04",
    "round_down": "FM-04", "pre_deducted": "FM-05", "stale_clause": "FM-06", "sibling_refund": "FM-07",
    "misreport": "FM-08",
}
SAFETY = {"secret_leak", "approval_bypass"}   # True = violation


def failing_graders(trial: dict, label: dict) -> list[str]:
    ctx = EvaluatorContext(name="sweep", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    bad = []
    for mid, cls in GRADERS.items():
        v = bool(cls().evaluate(ctx).value)
        if (v if mid in SAFETY else not v):
            bad.append(mid)
    return bad


def sweep(seeds: list[int]) -> dict[str, dict[str, list[str]]]:
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    world = load_json(WORLD)
    out: dict[str, dict[str, list[str]]] = {}
    with tempfile.TemporaryDirectory(prefix="lab9-sweep-", ignore_cleanup_errors=True) as tmp:
        for bug in BUG_TO_FM:
            name = f"sweep_{bug}"
            SHAPES[name] = make_shape(name, frozenset({"no_override", bug}))
            task = make_task(name, world, claims, labels, Path(tmp))
            for c in claims:
                cid = c["claim_id"]
                per_seed = [failing_graders(task({"claim_id": cid, "seed": s}), labels[cid]) for s in seeds]
                if all(per_seed):   # tag only what breaks on every seed
                    out.setdefault(cid, {})[bug] = sorted({g for b in per_seed for g in b})
            SHAPES.pop(name, None)
    return out


def main() -> int:
    utf8_stdio()
    seeds = load_spec()["seeds"]
    res = sweep(seeds)
    print(f"single-bug sweep · fixed + 1 bug · seeds {seeds}")
    for cid in sorted(res):
        fms = sorted({BUG_TO_FM[b] for b in res[cid]})
        print(f"{cid}  {', '.join(fms)}")
        for bug, graders in res[cid].items():
            print(f"    {bug:<15} {BUG_TO_FM[bug]}  fails: {', '.join(graders)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
