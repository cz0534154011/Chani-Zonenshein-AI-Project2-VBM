"""Tests for the routing functions of the subgraph and the main graph (every path)."""

import pytest

from vbm.schemas import BuyerDecision, Offer
from vbm.nodes import route_after_confirm, route_after_review, route_after_verify, route_start
from vbm.subgraph import route_after_buyer, route_after_guardrail, route_after_seller

OFFER = Offer(unit_price=400, delivery_days=30, payment_terms="net60")


def decision(action):
    return BuyerDecision(action=action, offer=OFFER if action != "walk_away" else None,
                         message="m", rationale="r")


@pytest.mark.parametrize("pending, expected", [
    (decision("accept"), "guardrail"),
    (decision("counter"), "guardrail"),
    (decision("walk_away"), "finalize"),
    (None, "guardrail"),
])
def test_route_after_buyer(pending, expected):
    assert route_after_buyer({"pending_decision": pending}) == expected


@pytest.mark.parametrize("feedback, pending, expected", [
    ("Total exceeds budget.", decision("counter"), "buyer_decide"),
    (None, decision("counter"), "seller_respond"),
    (None, decision("accept"), "finalize"),
    (None, decision("walk_away"), "finalize"),
])
def test_route_after_guardrail(feedback, pending, expected):
    assert route_after_guardrail({"guardrail_feedback": feedback, "pending_decision": pending}) == expected


@pytest.mark.parametrize("status, round_no, expected", [
    ("accepted", 3, "finalize"),
    ("quit", 3, "finalize"),
    ("open", 3, "buyer_decide"),
    ("open", 8, "buyer_decide"),  # final turn of the buyer (P3)
])
def test_route_after_seller(status, round_no, expected):
    assert route_after_seller({"seller_status": status, "round": round_no, "max_rounds": 8}) == expected


@pytest.mark.parametrize("state, expected", [
    ({"raw_request": "500 chairs"}, "parse_request"),
    ({"raw_request": None}, "plan_simulations"),
    ({}, "plan_simulations"),
])
def test_route_start(state, expected):
    assert route_start(state) == expected


@pytest.mark.parametrize("confirmed, expected", [(True, "plan_simulations"), (False, "parse_request")])
def test_route_after_confirm(confirmed, expected):
    assert route_after_confirm({"terms_confirmed": confirmed}) == expected


@pytest.mark.parametrize("action, expected", [
    ("report", "write_report"),
    ("change_terms", "plan_simulations"),
    ("change_seller", "plan_simulations"),
    ("invalid", "findings_review"),
])
def test_route_after_review(action, expected):
    assert route_after_review({"user_choice": {"action": action}}) == expected


@pytest.mark.parametrize("ok, fallback, expected", [
    (True, False, "debrief"),
    (False, True, "debrief"),
    (False, False, "write_report"),
])
def test_route_after_verify(ok, fallback, expected):
    assert route_after_verify({"report_ok": ok, "report_is_fallback": fallback}) == expected
