"""Regression test from docs/trace_case.md: seeded_regression C-002@11.

First wrong step = event 3 `model_override {"delay_days": 5}`: the agent let the ticket
("trễ 5 ngày") overwrite the DB fact (delay_days = 2), so it quoted and refunded 20.000đ
for a claim that must be denied (FM-03, ticket_trust).
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape: str):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", 11)
    ctx = EvaluatorContext(name="C-002@11", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {
        "db_fact_kept": graders.DbFactKept().evaluate(ctx).value,
        "refund_amount_correct": graders.RefundAmountCorrect().evaluate(ctx).value,
    }


def test_lab9_trace_case_regression_is_caught():
    trial, verdict = _grade("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    assert "model_override" in kinds                    # the first wrong step is in the trace
    assert verdict == {"db_fact_kept": False, "refund_amount_correct": False}
    assert trial["snapshot"]["refund_vnd"] == 20000     # money moved on a claim labelled denied


def test_lab9_trace_case_fixed_passes():
    trial, verdict = _grade("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert verdict == {"db_fact_kept": True, "refund_amount_correct": True}
    assert trial["snapshot"]["refund_vnd"] == 0
