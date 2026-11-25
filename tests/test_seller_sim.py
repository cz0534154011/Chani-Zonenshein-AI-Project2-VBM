"""Tests for the simulated supplier (vbm.domain.seller_sim), its texts (vbm.adapters.texts) and the generator."""

import pytest

from vbm.adapters.texts import seller_message
from vbm.domain.economics import seller_floor
from vbm.domain.scenario_generator import generate_limits, profile_for_style, profiles_for_all_styles
from vbm.domain.schemas import Offer, validate_buyer_terms
from vbm.domain.seller_sim import ask_price, opening_offer, respond

LIMITS = {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14}
T = 8


def seller(style="balanced"):
    return profile_for_style(LIMITS, style)


def offer(price, days=21, terms="advance"):
    return Offer(unit_price=price, delivery_days=days, payment_terms=terms)


# 1. עקומת הוויתורים תואמת את הטבלה באפיון (מעוגל לשלם)
@pytest.mark.parametrize("style, expected", [
    ("tough",    {1: 480, 2: 478, 4: 461, 6: 417, 7: 380, 8: 330}),
    ("balanced", {1: 461, 2: 443, 4: 405, 6: 368, 7: 349, 8: 330}),
    ("flexible", {1: 427, 2: 405, 4: 374, 6: 350, 7: 340, 8: 330}),
])
def test_concession_curve_matches_spec_table(style, expected):
    for t, value in expected.items():
        assert abs(ask_price(seller(style), t, T) - value) <= 0.5


def test_opening_offer_is_anchor():
    assert opening_offer(seller()) == offer(480, 21, "advance")


# 2. כלל 1: מועד מהיר מהמינימום - הספק דוחה את הסעיף ומציע את המועד המינימלי
def test_rule1_delivery_below_min_days():
    r = respond(seller(), offer(470, days=10), round_no=1, max_rounds=T, low_offer_streak=0)
    assert r["status"] == "open" and r["reason"] == "delivery_below_min"
    assert all(o.delivery_days in (14, 21) for o in r["offers"])
    assert any(o.delivery_days == 14 for o in r["offers"])


# 3. כלל 2: הצעה שעומדת בדרישה המותאמת - מקבל; אגורה פחות - לא
def test_rule2_accept_at_adjusted_ask():
    need = round(442.5 * 1.02, 2)  # balanced, round 2, net60, standard days
    assert respond(seller(), offer(need, terms="net60"), 2, T, 0)["status"] == "accepted"
    assert respond(seller(), offer(need - 0.01, terms="net60"), 2, T, 0)["status"] == "open"


# 4. כלל 3: שלוש הצעות ברצף מתחת ל-60% מהרצפה - פורש; הצעה סבירה מאפסת את הספירה
def test_rule3_quit_after_three_low_offers():
    s, low = seller(), offer(190)  # 60% of 330 = 198
    r1 = respond(s, low, 1, T, 0)
    r2 = respond(s, low, 2, T, r1["low_offer_streak"])
    r3 = respond(s, low, 3, T, r2["low_offer_streak"])
    assert (r1["status"], r2["status"], r3["status"]) == ("open", "open", "quit")
    assert respond(s, offer(300), 3, T, 2)["low_offer_streak"] == 0


# 5. כלל 4: אחרת - הצעה נגדית בדיוק בדרישה של הסבב
def test_rule4_counter_at_ask():
    r = respond(seller(), offer(350), 4, T, 0)
    assert r["status"] == "open" and [o.unit_price for o in r["offers"]] == [405.0]


# 6. הרצפה אף פעם לא נשברת - בכל סגנון, סבב, תנאי תשלום ומועד
def test_floor_never_broken():
    for style in ("tough", "balanced", "flexible"):
        for t in range(1, T + 1):
            for terms in ("advance", "net30", "net60"):
                for days in (14, 18, 21, 30):
                    r = respond(seller(style), offer(100, days, terms), t, T, 0)
                    for o in r["offers"]:
                        assert o.unit_price >= seller_floor(seller(style), o.payment_terms, o.delivery_days)


# 7. תנאי יקר - תמיד שתי אפשרויות; תנאי זול - אפשרות אחת
def test_two_options_on_costly_terms():
    r = respond(seller(), offer(350, terms="net60"), 4, T, 0)
    own, theirs = r["offers"]
    assert own.payment_terms == "advance" and theirs.payment_terms == "net60"
    assert theirs.unit_price == round(own.unit_price * 1.02, 2)
    assert len(respond(seller(), offer(350, days=30), 4, T, 0)["offers"]) == 1


# 8. אותו מצב - אותה תגובה
def test_deterministic():
    args = (seller("tough"), offer(360, 18, "net30"), 5, T, 1)
    assert respond(*args) == respond(*args)


def test_final_round_message():
    en, _ = seller_message(respond(seller(), offer(300), 8, T, 0), offer(300), seller(), 8, T)
    assert "final offer" in en


def test_messages_never_reveal_floor():
    s = profile_for_style({"list_price": 487.0, "min_price": 333.37, "standard_days": 21, "min_days": 13}, "tough")
    for t in range(1, T):
        en, he = seller_message(respond(s, offer(250), t, T, 0), offer(250), s, t, T)
        assert "333.37" not in en and "333.37" not in he


# 9. מחולל הספקים
BUYER = validate_buyer_terms({"product": "chair", "quantity": 500, "max_budget_total": 210000,
                              "target_total": 160000, "deadline_days": 30, "preferred_terms": "net60"})


def test_generator_same_seed_same_limits():
    assert generate_limits(BUYER, 7) == generate_limits(BUYER, 7)
    assert generate_limits(BUYER, 7) != generate_limits(BUYER, 8)


def test_generator_known_overrides_draw():
    limits = generate_limits(BUYER, 7, {"list_price": 450})
    assert limits["list_price"] == 450
    assert generate_limits(BUYER, 7, {"list_price": 450})["standard_days"] == generate_limits(BUYER, 7)["standard_days"]


def test_generator_limits_are_valid():
    for seed in range(200):
        limits = generate_limits(BUYER, seed)
        profile_for_style(limits, "tough")  # raises if invalid
        assert limits["min_days"] >= 5


def test_all_styles_share_limits():
    profiles = profiles_for_all_styles(generate_limits(BUYER, 3))
    assert {p["min_price"] for p in profiles.values()} == {generate_limits(BUYER, 3)["min_price"]}
    assert [p["style"] for p in profiles.values()] == ["tough", "balanced", "flexible"]
