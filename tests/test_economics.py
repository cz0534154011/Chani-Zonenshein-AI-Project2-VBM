"""Tests for vbm.economics and the validation helpers in vbm.schemas."""

import pytest
from pydantic import ValidationError

from vbm.economics import compute_zopa, seller_floor, with_variant
from vbm.schemas import BuyerDecision, validate_buyer_terms

SELLER = {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14, "style": "balanced"}

# הדוגמה מסעיף 8 באפיון
BUYER = validate_buyer_terms({
    "product": "office chair", "quantity": 500,
    "max_budget_total": 210000, "target_total": 160000,
    "deadline_days": 30, "preferred_terms": "net60",
})


def test_floor_by_payment_terms():
    assert seller_floor(SELLER, "advance", 21) == 330.0
    assert seller_floor(SELLER, "net30", 21) == 333.3
    assert seller_floor(SELLER, "net60", 21) == 336.6


def test_fast_delivery_premium_multiplies():
    assert seller_floor(SELLER, "advance", 20) == 343.2
    assert seller_floor(SELLER, "net60", 15) == 350.06


def test_faster_than_min_days_is_impossible():
    assert seller_floor(SELLER, "advance", 13) is None
    assert seller_floor(SELLER, "advance", 14) is not None


def test_spec_example_base():
    assert compute_zopa(BUYER, SELLER) == {"zopa_low": 336.6, "zopa_high": 420.0, "zopa_exists": True}


def test_payment_variant_lowers_zopa_low():
    assert compute_zopa(with_variant(BUYER, "payment"), SELLER)["zopa_low"] == 330.0


def test_delivery_variant_removes_fast_premium():
    buyer = {**BUYER, "preferred_days": 15}
    assert compute_zopa(buyer, SELLER)["zopa_low"] == 350.06
    assert compute_zopa(with_variant(buyer, "delivery"), SELLER)["zopa_low"] == 336.6


def test_delivery_variant_never_crosses_deadline():
    buyer = {**BUYER, "deadline_days": 10, "preferred_days": 10}
    for variant in ("base", "payment", "delivery"):
        zopa = compute_zopa(with_variant(buyer, variant), SELLER)
        assert zopa["zopa_low"] is None and zopa["zopa_exists"] is False


def test_no_zopa_on_price():
    buyer = {**BUYER, "max_budget_total": 150000, "target_total": 140000}
    zopa = compute_zopa(buyer, SELLER)
    assert zopa["zopa_high"] == 300.0 and zopa["zopa_exists"] is False


def test_preferred_days_defaults_to_deadline():
    assert BUYER["preferred_days"] == 30 and BUYER["flexible_on"] == []


def test_preferred_days_after_deadline_rejected():
    with pytest.raises(ValueError):
        validate_buyer_terms({**BUYER, "preferred_days": 40})


def test_counter_requires_offer():
    with pytest.raises(ValidationError):
        BuyerDecision(action="counter", offer=None, message="x", rationale="y")
