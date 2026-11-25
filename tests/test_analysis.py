"""Tests for vbm.application.analysis (ReportData), the report texts and the report number check."""

from vbm.adapters.texts import build_preview, concession_text, fallback_report, patience_text, price_range_text
from vbm.application.analysis import (analyze_results, current_batch, decisive_concession, lowest_allowed_offer,
                                      patience_round, price_gap)
from vbm.application.numbers import unverified_numbers
from vbm.domain.schemas import Offer

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


def seller_offers(round_no, *offers):
    return {"round": round_no, "speaker": "seller", "message": "", "message_he": "", "rationale": None,
            "offers": [Offer(unit_price=p, delivery_days=d, payment_terms=t) for p, d, t in offers]}


def test_lowest_offer_counts_only_terms_the_variant_allows():
    transcript = [seller_offers(0, (480, 21, "advance")), seller_offers(1, (430, 21, "advance"), (445, 30, "net60")),
                  seller_offers(2, (420, 40, "net60"))]
    base = result("tough", "base", reason="max_rounds", transcript=transcript)
    payment = result("tough", "payment", reason="max_rounds", transcript=transcript)
    assert lowest_allowed_offer(base, BUYER).unit_price == 445  # advance and 40 days are not allowed
    assert lowest_allowed_offer(payment, BUYER).unit_price == 430  # advance is allowed, 40 days is not


def test_price_gap_per_variant():
    base = [seller_offers(1, (440, 30, "net60"))]
    delivery = [seller_offers(1, (415, 30, "net60"))]
    results = [result("tough", "base", reason="max_rounds", transcript=base),
               result("tough", "payment", reason="max_rounds", transcript=[seller_offers(1, (430, 30, "advance"))]),
               result("tough", "delivery", 415, transcript=delivery)]
    gap = price_gap(results, BUYER)
    assert gap["budget_per_unit"] == 420 and gap["base_has_gap"]
    assert gap["variants"]["base"]["gap_per_unit"] == 20 and gap["variants"]["base"]["required_total"] == 220000
    assert gap["variants"]["payment"]["gap_per_unit"] == 10 and not gap["variants"]["payment"]["closes"]
    assert gap["variants"]["delivery"]["closes"]
    data = analyze_results(results, BUYER)
    assert "220000" in build_preview(data) and "סוגרת את הפער" in build_preview(data)
    assert unverified_numbers(fallback_report(data), data) == []
    assert "## מה יסגור את הפער" in fallback_report(data)


def test_no_gap_section_when_the_base_closes():
    results = [result(s, v, 400, transcript=[seller_offers(1, (400, 30, "net60"))])
               for s in ("tough", "balanced", "flexible") for v in ("base", "payment", "delivery")]
    data = analyze_results(results, BUYER)
    assert not data["price_gap"]["base_has_gap"] and "מה יסגור את הפער" not in fallback_report(data)


def test_patience_text_covers_every_case():
    data = {"patience": None, "patience_threshold_percent": 90, "max_rounds": 8,
            "simulations": [{"style": "tough", "variant": "base", "rounds": 8}]}
    assert "סבלנות רבה" in patience_text(data)
    data["simulations"][0]["rounds"] = 3
    assert "הסתיימה בסבב 3" in patience_text(data)
    data["simulations"] = []
    assert "לא נבדק ספק קשוח" in patience_text(data)
    data["patience"] = 5
    assert "בסבב 5 מתוך 8" in patience_text(data)


def test_price_range_text_single_price_and_range():
    assert price_range_text({"min": 2500, "max": 2500}) == "כל עסקאות הבסיס נסגרו ב-2500 ליחידה."
    assert "בין 380 ל-400" in price_range_text({"min": 380, "max": 400})
    assert "לא נסגרה" in price_range_text(None)


def test_concession_text_gives_the_reason():
    converted = [result("tough", "base", 400), result("balanced", "base", reason="max_rounds"),
                 result("balanced", "payment", 410), result("tough", "payment", 400)]
    data = analyze_results(converted, BUYER)
    assert "סימולציה אחת" in concession_text(data) and "מאוזן" in concession_text(data)
    cheaper = analyze_results([result("tough", "base", 400), result("tough", "delivery", 380)], BUYER)
    assert "מ-400" in concession_text(cheaper) and "ל-380" in concession_text(cheaper)
    flat = analyze_results([result("tough", "base", 400), result("tough", "payment", 399)], BUYER)
    assert "אף גמישות" in concession_text(flat)
    assert unverified_numbers(fallback_report(data), data) == []
