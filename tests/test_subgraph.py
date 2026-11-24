"""Full runs of the negotiation subgraph with a scripted buyer (no model calls)."""

import pytest

import vbm.subgraph
from vbm.scenario_generator import profile_for_style
from vbm.schemas import BuyerDecision, Offer
from vbm.subgraph import subgraph

LIMITS = {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14}
BUYER = {"product": "office chair", "quantity": 500, "max_budget_total": 210000,
         "target_total": 160000, "deadline_days": 30, "preferred_terms": "net60"}


class ScriptedBuyer:
    """Stands in for the buyer model: returns prepared decisions in order."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.decisions.pop(0)


def counter(price, days=30, terms="net60", message=None):
    offer = Offer(unit_price=price, delivery_days=days, payment_terms=terms)
    text = message or f"I can offer {price} per unit, delivery in {days} days, net 60."
    return BuyerDecision(action="counter", offer=offer, message=text, rationale="scripted")


def walk_away():
    return BuyerDecision(action="walk_away", offer=None, message="No deal, thank you.", rationale="scripted")


def run(decisions, style="balanced", limits=LIMITS, monkeypatch=None):
    buyer = ScriptedBuyer(decisions)
    monkeypatch.setattr(vbm.subgraph, "get_buyer_decider", lambda: buyer)
    inputs = {"buyer": BUYER, "seller": profile_for_style(limits, style), "variant": "base",
              "batch_id": 1, "max_rounds": 8}
    result = subgraph.invoke(inputs)["sim_results"][0]
    return result, buyer


def test_deal_when_offer_reaches_the_ask(monkeypatch):
    prices = [350, 360, 370, 380, 390, 400, 410, 420]
    result, _ = run([counter(p) for p in prices], monkeypatch=monkeypatch)
    assert result["outcome"] == "deal"
    assert result["final"].unit_price == 400 and result["rounds"] == 6
    assert result["first_offer"].unit_price == 350 and not result["accepted_opening"]
    assert result["guardrail_hits"] == 0 and result["no_deal_reason"] is None
    speakers = [e["speaker"] for e in result["transcript"]]
    assert speakers[0] == "seller" and len(speakers) == 13  # opening + 6 x (buyer, seller)


def test_accept_over_budget_is_retried_then_clamped(monkeypatch):
    opening = Offer(unit_price=480, delivery_days=21, payment_terms="advance")
    accept = BuyerDecision(action="accept", offer=opening, message="Deal.", rationale="scripted")
    result, buyer = run([accept, accept, accept, walk_away()], monkeypatch=monkeypatch)
    assert buyer.calls == 4
    assert result["guardrail_hits"] == 3
    clamped = result["transcript"][1]["offers"][0]
    assert clamped.unit_price == 420 and clamped.payment_terms == "net60"
    assert result["outcome"] == "no_deal" and result["no_deal_reason"] == "buyer_walk_away"


def test_final_turn_counter_becomes_walk_away(monkeypatch):
    decisions = [counter(300) for _ in range(8)] + [counter(300)] * 3
    result, buyer = run(decisions, monkeypatch=monkeypatch)
    assert buyer.calls == 11 and result["rounds"] == 8
    assert result["outcome"] == "no_deal" and result["no_deal_reason"] == "max_rounds"
    assert result["guardrail_hits"] == 3


def test_seller_quits_after_three_low_offers(monkeypatch):
    result, _ = run([counter(100)] * 3, monkeypatch=monkeypatch)
    assert result["outcome"] == "no_deal" and result["no_deal_reason"] == "seller_quit"


def test_delivery_impossible_takes_precedence(monkeypatch):
    slow = {**LIMITS, "standard_days": 40, "min_days": 35}
    result, _ = run([walk_away()], limits=slow, monkeypatch=monkeypatch)
    assert result["no_deal_reason"] == "delivery_impossible"


def test_message_numbers_must_match_offer(monkeypatch):
    wrong = counter(350, message="I can offer 340 per unit, delivery in 30 days, net 60.")
    result, buyer = run([wrong, counter(350), walk_away()], monkeypatch=monkeypatch)
    assert result["message_mismatch"] == 1 and result["guardrail_hits"] == 1
    assert buyer.calls == 3


@pytest.mark.parametrize("style", ["tough", "balanced", "flexible"])
def test_every_style_closes_within_budget(style, monkeypatch):
    result, _ = run([counter(420)] * 9, style=style, monkeypatch=monkeypatch)
    assert result["outcome"] == "deal"
    assert result["final"].unit_price * BUYER["quantity"] <= BUYER["max_budget_total"]
