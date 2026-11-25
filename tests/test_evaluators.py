"""Tests for the evaluation target and the code evaluators (fake models, no LangSmith)."""

from dataclasses import replace

import pytest

from vbm.adapters.llm_gateways import LLMBuyerDecider, LLMReportWriter
from vbm.application.dto import BuyerDecision
from vbm.domain.schemas import Offer
from vbm.infrastructure.evaluation.evaluators import (
    EVALUATORS, accepted_opening_rate, budget_violation, close_rate, decisive_concession_correct,
    feasibility_correct, first_offer_position, guardrail_hits, price_score, report_numbers_match,
    make_target, summary_evaluator, summary_metrics,
)
from vbm.infrastructure.wiring import default_ports

WIDE = {"zopa_exists": True, "zopa_low": 300.0, "zopa_high": 400.0, "decisive_concession": "none", "category": "wide"}
NO_ZOPA = {"zopa_exists": False, "zopa_low": 450.0, "zopa_high": 400.0, "decisive_concession": "payment",
           "category": "no_zopa_price"}
INPUTS = {"buyer": {"max_budget_total": 40000, "quantity": 100}}


def sim(variant="base", outcome="deal", price=350.0, first=320.0, opening=False, hits=0, quantity=100):
    return {"style": "balanced", "variant": variant, "outcome": outcome,
            "unit_price": price if outcome == "deal" else None,
            "total": round(price * quantity, 2) if outcome == "deal" else None,
            "first_offer_price": first, "accepted_opening": opening, "guardrail_hits": hits}


def outputs(sims, concession="none", report_ok=True):
    return {"sims": sims, "report_ok": report_ok, "report_is_fallback": not report_ok,
            "report_data": {"decisive_concession": concession}}


def test_feasibility_compares_base_deals_with_zopa_exists():
    closed = outputs([sim(), sim(outcome="no_deal"), sim(variant="payment", outcome="no_deal")])
    none_closed = outputs([sim(outcome="no_deal"), sim(variant="payment")])
    assert feasibility_correct(closed, WIDE)["score"] == 1.0
    assert feasibility_correct(none_closed, WIDE)["score"] == 0.0
    assert feasibility_correct(none_closed, NO_ZOPA)["score"] == 1.0


def test_close_rate_counts_only_base_and_only_with_zopa():
    out = outputs([sim(), sim(outcome="no_deal"), sim(outcome="no_deal"), sim(variant="delivery")])
    assert close_rate(out, WIDE)["score"] == pytest.approx(1 / 3)
    assert close_rate(out, NO_ZOPA)["score"] is None


def test_price_score_is_position_in_zopa_clipped():
    out = outputs([sim(price=300.0), sim(price=400.0), sim(price=250.0), sim(variant="payment", price=400.0)])
    assert price_score(out, WIDE)["score"] == pytest.approx((1.0 + 0.0 + 1.0) / 3)
    assert price_score(outputs([sim(price=375.0)]), WIDE)["score"] == pytest.approx(0.25)


def test_price_score_not_counted_without_zopa_or_without_base_deal():
    assert price_score(outputs([sim()]), NO_ZOPA)["score"] is None
    result = price_score(outputs([sim(outcome="no_deal"), sim(variant="payment")]), WIDE)
    assert result["score"] is None and result["comment"] == "no base deal"


def test_decisive_concession_and_report_flag():
    assert decisive_concession_correct(outputs([], concession="payment"), NO_ZOPA)["score"] == 1.0
    assert decisive_concession_correct(outputs([], concession="none"), NO_ZOPA)["score"] == 0.0
    assert report_numbers_match(outputs([]))["score"] == 1.0
    assert report_numbers_match(outputs([], report_ok=False))["score"] == 0.0


def test_budget_violation_checks_every_variant():
    assert budget_violation(INPUTS, outputs([sim(price=400.0), sim(variant="payment", price=399.0)]))["score"] == 0.0
    assert budget_violation(INPUTS, outputs([sim(), sim(variant="delivery", price=400.01)]))["score"] == 1.0


def test_diagnostics():
    out = outputs([sim(first=250.0, opening=True, hits=2), sim(first=350.0, hits=1), sim(variant="payment", first=400.0)])
    assert accepted_opening_rate(out)["score"] == pytest.approx(1 / 3)
    assert first_offer_position(out, WIDE)["score"] == pytest.approx(0.0)
    assert first_offer_position(out, NO_ZOPA)["score"] is None
    assert guardrail_hits(out)["score"] == 3.0


def test_errored_run_is_not_counted():
    for evaluator in (feasibility_correct, close_rate, price_score, decisive_concession_correct, first_offer_position):
        assert evaluator({}, WIDE)["score"] is None
    assert budget_violation(INPUTS, {})["score"] is None
    for evaluator in (report_numbers_match, accepted_opening_rate, guardrail_hits):
        assert evaluator({})["score"] is None


def test_summary_metrics_skip_runs_where_a_metric_does_not_count():
    good = outputs([sim(price=300.0), sim(price=300.0), sim(price=300.0)], concession="none")
    half = outputs([sim(price=350.0), sim(outcome="no_deal"), sim(outcome="no_deal")], concession="payment")
    no_zopa = outputs([sim(outcome="no_deal")], concession="payment")
    metrics = summary_metrics([good, half, no_zopa, None], [WIDE, WIDE, NO_ZOPA, WIDE])
    assert metrics == {"mean_price_score": 0.75, "feasibility_accuracy": 1.0,
                       "decisive_accuracy": round(2 / 3, 4), "mean_close_rate": round(2 / 3, 4)}
    keys = [r["key"] for r in summary_evaluator([good], [WIDE])["results"]]
    assert keys == list(metrics)


class Fixed:
    """Stands in for the report model: always returns the same text."""

    def invoke(self, messages):
        return "## דוח\nאלה סימולציות בלבד."


class SteadyBuyer:
    """Counters at 400 every round and walks away on the final turn."""

    def invoke(self, messages):
        if "final offer" in messages[-1].content.splitlines()[-1]:
            return BuyerDecision(action="walk_away", offer=None, message="No deal.", rationale="scripted")
        offer = Offer(unit_price=400, delivery_days=30, payment_terms="net60")
        return BuyerDecision(action="counter", offer=offer, message="I can offer 400 per unit, delivery in 30 days, net 60.",
                             rationale="scripted")


def test_target_runs_the_graph_with_the_fixed_policy():
    ports = replace(default_ports(), report_writer=LLMReportWriter(lambda: Fixed()),
                    buyer_decider=LLMBuyerDecider(lambda: SteadyBuyer()))
    inputs = {"buyer": {"product": "office chair", "quantity": 500, "max_budget_total": 210000, "target_total": 160000,
                        "deadline_days": 30, "preferred_days": 30, "preferred_terms": "net60", "flexible_on": []},
              "seller_profiles": {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14},
              "max_rounds": 8, "seed": 7}
    out = make_target("v1", ports)(inputs)
    assert set(out) == {"report_data", "report_ok", "report_is_fallback", "sims"}
    assert len(out["sims"]) == 9 and out["report_ok"]
    assert all("transcript" not in s for s in out["sims"])
    reference = {"zopa_exists": True, "zopa_low": 336.6, "zopa_high": 420.0, "decisive_concession": "payment",
                 "category": "wide"}
    for evaluator in EVALUATORS:
        args = {"inputs": inputs, "outputs": out, "reference_outputs": reference}
        params = evaluator.__code__.co_varnames[:evaluator.__code__.co_argcount]
        score = evaluator(**{p: args[p] for p in params})["score"]
        assert score is None or isinstance(score, float)
    assert budget_violation(inputs, out)["score"] == 0.0
