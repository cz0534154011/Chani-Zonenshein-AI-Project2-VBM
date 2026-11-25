"""Tests for the prompts: no supplier secrets in the buyer prompt, a Hebrew-only view for the report prompt."""

import inspect
import json
import re

import vbm.subgraph
from vbm.analysis import analyze_results
from vbm.economics import seller_floor
from vbm.nodes import numbers_in_text, unverified_numbers
from vbm.prompts.buyer_v1 import build_buyer_prompt
from vbm.prompts.report import build_report_prompt
from vbm.scenario_generator import profile_for_style
from vbm.schemas import BuyerDecision, Offer
from vbm.subgraph import subgraph

# מספרים ייחודיים שלא יכולים להופיע בפרומפט במקרה
SECRET = {"list_price": 487.0, "min_price": 333.37, "standard_days": 21, "min_days": 13}
BUYER = {"product": "office chair", "quantity": 500, "max_budget_total": 210000,
         "target_total": 160000, "deadline_days": 30, "preferred_terms": "net60"}


class RecordingBuyer:
    """Counters at a fixed offer, walks away on turn 6, and keeps every prompt it was given."""

    def __init__(self, days):
        self.days = days
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append("\n".join(m.content for m in messages))
        if len(self.prompts) >= 6:
            return BuyerDecision(action="walk_away", offer=None, message="No deal, thank you.", rationale="scripted")
        offer = Offer(unit_price=400, delivery_days=self.days, payment_terms="net60")
        return BuyerDecision(action="counter", offer=offer, rationale="scripted",
                             message=f"I can offer 400 per unit, delivery in {self.days} days, net 60.")


def prompt_numbers(monkeypatch, days, style="tough", variant="base"):
    buyer = RecordingBuyer(days)
    monkeypatch.setattr(vbm.subgraph, "get_buyer_decider", lambda: buyer)
    subgraph.invoke({"buyer": BUYER, "seller": profile_for_style(SECRET, style), "variant": variant,
                     "batch_id": 1, "max_rounds": 8})
    return {float(t.replace(",", "")) for p in buyer.prompts for t in numbers_in_text(p)}


def all_floors() -> set[float]:
    seller = profile_for_style(SECRET, "tough")
    return {seller_floor(seller, terms, days) for terms in ("advance", "net30", "net60") for days in (13, 21)}


def test_buyer_prompt_takes_only_buyer_data():
    assert list(inspect.signature(build_buyer_prompt).parameters) == ["buyer", "transcript", "guardrail_feedback"]


def test_min_price_and_floors_never_reach_the_buyer(monkeypatch):
    for style in ("tough", "balanced", "flexible"):
        for variant in ("base", "payment", "delivery"):
            seen = prompt_numbers(monkeypatch, 30, style, variant)
            assert not seen & all_floors(), (style, variant)


def test_min_days_hidden_unless_the_buyer_asks_too_fast(monkeypatch):
    assert 13.0 not in prompt_numbers(monkeypatch, 30)
    # כלל 1 של הספק: בקשה מהירה מדי חושפת את המועד המינימלי בכוונה
    assert 13.0 in prompt_numbers(monkeypatch, 10)


def sim(style, variant, price, lowest, reason=None):
    final = Offer(unit_price=price, delivery_days=30, payment_terms="net60") if price else None
    seller = {"round": 1, "speaker": "seller", "message": "", "message_he": "", "rationale": None,
              "offers": [Offer(unit_price=lowest, delivery_days=30, payment_terms="net60")]}
    return {"batch_id": 1, "style": style, "variant": variant, "outcome": "deal" if price else "no_deal",
            "final": final, "rounds": 8, "no_deal_reason": reason, "guardrail_hits": 0, "message_mismatch": 0,
            "first_offer": None, "accepted_opening": False, "transcript": [seller]}


def test_report_prompt_is_hebrew_only_and_has_the_gap():
    results = [sim(s, "base", None, 440, "max_rounds") for s in ("tough", "balanced", "flexible")]
    results += [sim(s, "delivery", 415, 415) for s in ("tough", "balanced", "flexible")]
    results += [sim(s, "payment", None, 430, "buyer_walk_away") for s in ("tough", "balanced", "flexible")]
    data = analyze_results(results, BUYER)
    user = build_report_prompt(data, [])[1].content
    view = json.loads(user.split("\n", 1)[1])
    assert "פער המחיר" in view and "null" not in user
    assert not re.search(r"[A-Za-z]", user.replace("office chair", ""))
    assert unverified_numbers(user, data) == []
