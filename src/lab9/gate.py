"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    man = pr.get("manifest") or {}
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. Numbers that cannot be compared: NaN / inf anywhere in the reported metrics.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (not a finite number)")

    # 2. Row count must equal items x seeds; no (item, seed) may appear twice.
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = len(keys) - len(set(keys))
    if dups:
        problems.append(f"{dups} duplicated (item, seed) row(s)")

    # 3. Same (item, seed) set and same seeds as the baseline: no cherry-picked items or seeds.
    base_rows = base.get("rows") or []
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = len(base_keys - set(keys)), len(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {miss} missing, {extra} extra")
    if sorted(man.get("seeds") or []) != sorted((base.get("manifest") or {}).get("seeds") or []):
        problems.append(f"seeds {man.get('seeds')} differ from baseline {(base.get('manifest') or {}).get('seeds')}")

    # 4. Crashed graders: reported failures, or a graded metric that is None/NaN on a row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    for m in graded:
        broken = [r for r in rows if m not in r or r[m] is None
                  or (isinstance(r[m], float) and not math.isfinite(r[m]))]
        if broken:
            problems.append(f"{len(broken)} row(s) have no value for graded metric {m} (grader crash?)")

    # 5. Reported metrics must be what the rows say (a hand-edited summary).
    problems += _summary_mismatch(pr, graded)

    # 6. Slice tags per item must match the baseline's.
    def tags(rs: list[dict]) -> dict:
        return {r.get("item_id"): sorted(r.get("slices") or []) for r in rs}
    pt, bt = tags(rows), tags(base_rows)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags differ from baseline on {', '.join(relabelled[:5])}")
    per_item: dict = {}
    for r in rows:
        per_item.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    mixed = sorted(i for i, v in per_item.items() if len(v) > 1)
    if mixed:
        problems.append(f"item(s) with different slice tags across seeds: {', '.join(mixed[:5])}")

    # 7. Ratchet: on the same eval-set version thresholds may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _summary_mismatch(pr: dict, graded: list[str]) -> list[str]:
    rows, out = pr.get("rows") or [], []
    metrics = pr.get("metrics") or {}
    for m in graded:
        if m not in metrics or not rows:
            continue
        vals = [r.get(m) for r in rows if r.get(m) is not None]
        if m in ("secret_leak", "approval_bypass"):
            want = sum(bool(v) for v in vals)
        else:
            want = round(sum(bool(v) for v in vals) / len(vals), 4) if vals else None
        got = metrics[m]
        if want is None or got is None:
            continue
        if not isinstance(got, (int, float)) or abs(float(got) - float(want)) > 1e-4:
            out.append(f"metric {m} reported {got}, rows give {want}")
    return out


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    for key in ("max", "max_increase"):
        if key in base_th and (key not in th or th[key] > base_th[key]):
            out.append(f"{key} {base_th[key]} -> {th.get(key, 'removed')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"min {base_th['min']} -> {th.get('min', 'removed')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Spec in the PR vs the spec on main. Only enforced on the same eval-set version."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out = []
    now = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = now.get(bm["id"])
        if m is None:
            out.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {bm['id']} no longer blocking")
        out += [f"ratchet: metric {bm['id']} {x}" for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    now_s = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        key = (bs["name"], bs["metric"])
        sl = now_s.get(key)
        if sl is None:
            out.append(f"ratchet: slice {key[0]}/{key[1]} removed")
            continue
        if bs.get("blocking") and not sl.get("blocking"):
            out.append(f"ratchet: slice {key[0]}/{key[1]} no longer blocking")
        out += [f"ratchet: slice {key[0]}/{key[1]} {x}" for x in _looser(sl, bs)]
    if base_spec.get("seeds") and sorted(spec.get("seeds") or []) != sorted(base_spec["seeds"]):
        out.append(f"ratchet: seeds changed {base_spec['seeds']} -> {spec.get('seeds')}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            verdict = "missing"            # a slice with no items cannot vouch for anything
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: v for k, v in sl.items() if k in ("min", "no_significant_drop")}
        lines.append(f"  {sid:<40} {val!s:<8} n={len(a):<3} {json.dumps(th):<34} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
