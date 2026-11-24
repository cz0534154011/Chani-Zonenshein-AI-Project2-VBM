"""Tests for vbm.analysis (ReportData) and the report number check in vbm.nodes."""

from vbm.analysis import analyze_results, current_batch, decisive_concession, patience_round
from vbm.nodes import fallback_report, unverified_numbers
from vbm.schemas import Offer

BUYER = {"product": "office chair", "quantity": 500, "max_budget_total": 210000,
         "target_total": 160000, "deadline_days": 30, "preferred_days": 30, "preferred_terms": "net60"}


def result(style, variant, price=None, reason=None, transcript=None, batch=1):
    final = Offer(unit_price=price, delivery_days=30, payment_terms="net60") if price else None
    return {"batch_id": batch, "style": style, "variant": variant, "outcome": "deal" if price else "no_deal",
            "final": final, "rounds": 5, "no_deal_reason": reason, "guardrail_hits": 0, "message_mismatch": 0,
            "first_offer": None, "accepted_opening": False, "transcript": transcript or []}


def seller_entry(round_no, price):
    return {"round": round_no, "speaker": "seller", "message": "", "message_he": "", "rationale": None,
            "offers": [Offer(unit_price=price, delivery_days=21, payment_terms="advance")]}


def test_current_batch_keeps_only_that_batch():
    results = [result("tough", "base", 400, batch=1), result("tough", "base", 390, batch=2)]
    assert [r["final"].unit_price for r in current_batch(results, 2)] == [390]


def test_decisive_concession_by_price():
    results = [result("tough", "base", 400), result("tough", "payment", 380), result("tough", "delivery", 398)]
    assert decisive_concession(results) == "payment"


def test_decisive_concession_below_one_percent_is_none():
    results = [result("tough", "base", 400), result("tough", "payment", 398), result("tough", "delivery", 399)]
    assert decisive_concession(results) == "none"


def test_decisive_concession_turning_no_deal_into_deal():
    results = [result("tough", "base", reason="max_rounds"), result("tough", "payment", reason="max_rounds"),
               result("tough", "delivery", 410)]
    assert decisive_concession(results) == "delivery"


def test_patience_is_first_round_below_ninety_percent():
    transcript = [seller_entry(0, 480), seller_entry(1, 480), seller_entry(4, 440), seller_entry(5, 430), seller_entry(6, 417)]
    assert patience_round([result("tough", "base", 400, transcript=transcript)]) == 5


def test_report_data_and_number_check():
    results = [result(s, v, 400) for s in ("tough", "balanced", "flexible") for v in ("base", "payment", "delivery")]
    data = analyze_results(results, BUYER)
    assert data["feasibility"] == {"tough": True, "balanced": True, "flexible": True}
    assert data["price_range"] == {"min": 400, "max": 400} and data["decisive_concession"] == "none"
    assert unverified_numbers("ניתן לסגור ב-400 ליחידה, תקציב 210,000.", data) == []
    assert unverified_numbers("ניתן לסגור ב-385 ליחידה.", data) == ["385"]
    assert unverified_numbers(fallback_report(data), data) == []
