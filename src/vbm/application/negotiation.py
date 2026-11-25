"""VBM negotiation logic: turn order, the guardrail's checks and the outcome of one negotiation (no framework, no text)."""

import math
from typing import Literal, TypedDict

from vbm.application.dto import BuyerDecision
from vbm.application.numbers import NUMBER_RE
from vbm.application.policy import GUARDRAIL_MAX_RETRIES
from vbm.domain.economics import allowed_payment_terms, max_allowed_days, round_price
from vbm.domain.schemas import BuyerTerms, Offer, SellerProfile, TranscriptEntry

# בעיה שהמעקה מצא: קוד ונתונים; הטקסט נבנה ב-adapters.texts
Problem = tuple[str, dict]


class DecisionReview(TypedDict):
    outcome: Literal["pass", "retry", "force_walk_away", "force_counter"]
    offer: Offer | None  # pass: the checked offer; force_counter: the clamped offer; otherwise None
    problems: list[Problem]
    mismatch: bool


# האם הקונה בתור האחרון (אחרי ההצעה האחרונה של הספק)
def is_final_turn(round_no: int, max_rounds: int) -> bool:
    """True after the supplier's offer in the last round (P3)."""
    return round_no >= max_rounds


# מספר הסבב שבו נרשם תור הקונה בתמליל
def buyer_round(round_no: int, max_rounds: int) -> int:
    """Round number for the buyer's current turn."""
    return max_rounds if is_final_turn(round_no, max_rounds) else round_no + 1


# הפרות של הצעה מול הגבולות של הקונה בגרסה שלו
def offer_problems(buyer: BuyerTerms, offer: Offer) -> list[Problem]:
    """List the buyer limits that the offer breaks (empty list = valid)."""
    problems: list[Problem] = []
    total = round_price(offer.unit_price * buyer["quantity"])
    if total > buyer["max_budget_total"]:
        problems.append(("over_budget", {"total": total, "budget": buyer["max_budget_total"]}))
    if offer.delivery_days > max_allowed_days(buyer):
        problems.append(("late_delivery", {"days": offer.delivery_days, "limit": max_allowed_days(buyer)}))
    allowed = allowed_payment_terms(buyer)
    if offer.payment_terms not in allowed:
        problems.append(("payment_terms", {"allowed": allowed}))
    return problems


# האם יש בהודעה מספר שלא מופיע בהצעה, בתמליל או בנתוני ההזמנה
def has_message_mismatch(message: str, offer: Offer, buyer: BuyerTerms, transcript: list[TranscriptEntry], max_rounds: int) -> bool:
    """True if the message contains a number that is not backed by the offer or the conversation."""
    allowed = {offer.unit_price, float(offer.delivery_days), float(buyer["quantity"]), 30.0, 60.0}
    allowed.add(round_price(offer.unit_price * buyer["quantity"]))
    allowed.update(float(n) for n in range(1, max_rounds + 1))
    for entry in transcript:
        allowed.update(float(n.replace(",", "")) for n in NUMBER_RE.findall(entry["message"]))
        for o in entry["offers"]:
            allowed.update({o.unit_price, float(o.delivery_days), round_price(o.unit_price * buyer["quantity"])})
    for token in NUMBER_RE.findall(message):
        value = float(token.replace(",", ""))
        if not any(abs(value - a) <= 0.01 or (a >= 1000 and abs(value - a) <= 1) for a in allowed):
            return True
    return False


# ההצעה של הספק שהקונה מקבל; אם הספק הציע אפשרות אחת והקונה לא ציין - היא
def match_seller_offer(chosen: Offer | None, seller_offers: list[Offer]) -> Offer | None:
    """Return the supplier option the buyer accepts, or None if it does not match any option."""
    if chosen is None:
        return seller_offers[0] if len(seller_offers) == 1 else None
    for option in seller_offers:
        if (abs(option.unit_price - chosen.unit_price) <= 0.01 and option.delivery_days == chosen.delivery_days
                and option.payment_terms == chosen.payment_terms):
            return option
    return None


# הצמדת הצעה לערך המותר הקרוב (S4)
def clamp_offer(buyer: BuyerTerms, offer: Offer) -> Offer:
    """Nearest offer inside the buyer's budget, delivery limit and allowed payment terms."""
    max_unit = math.floor(buyer["max_budget_total"] / buyer["quantity"] * 100) / 100
    terms = offer.payment_terms if offer.payment_terms in allowed_payment_terms(buyer) else buyer["preferred_terms"]
    return Offer(
        unit_price=min(offer.unit_price, max_unit),
        delivery_days=min(offer.delivery_days, max_allowed_days(buyer)),
        payment_terms=terms,
    )


# המעקה: בודק את ההחלטה ומחליט - עוברת, חוזרת לתיקון, או שהקוד מחליט במקום הקונה
def review_decision(buyer: BuyerTerms, decision: BuyerDecision | None, seller_offers: list[Offer],
                    transcript: list[TranscriptEntry], final: bool, max_rounds: int, retries: int) -> DecisionReview:
    """Check the buyer decision; retry while retries < GUARDRAIL_MAX_RETRIES, then walk away (final turn) or clamp."""
    problems: list[Problem] = []
    checked = decision.offer if decision else None
    if decision is None:
        problems.append(("invalid_output", {}))
    elif decision.action == "accept":
        checked = match_seller_offer(decision.offer, seller_offers)
        if checked is None:
            problems.append(("accept_unknown_option", {}))
        else:
            problems += offer_problems(buyer, checked)
    elif decision.action == "counter":
        if final:
            problems.append(("counter_after_final", {}))
        else:
            problems += offer_problems(buyer, checked)
    mismatch = (decision is not None and checked is not None
                and has_message_mismatch(decision.message, checked, buyer, transcript, max_rounds))
    if mismatch:
        problems.append(("message_mismatch", {}))

    if not problems:
        return {"outcome": "pass", "offer": checked, "problems": [], "mismatch": mismatch}
    if retries < GUARDRAIL_MAX_RETRIES:
        return {"outcome": "retry", "offer": None, "problems": problems, "mismatch": mismatch}
    if final:
        return {"outcome": "force_walk_away", "offer": None, "problems": problems, "mismatch": mismatch}
    clamped = clamp_offer(buyer, checked or seller_offers[0])
    return {"outcome": "force_counter", "offer": clamped, "problems": problems, "mismatch": mismatch}


# שורת תמליל של הקונה
def buyer_entry(round_no: int, decision: BuyerDecision) -> TranscriptEntry:
    """Transcript entry for a buyer decision that passed the guardrail (or was set by it)."""
    return {"round": round_no, "speaker": "buyer",
            "offers": [decision.offer] if decision.offer else [],
            "message": decision.message, "message_he": None, "rationale": decision.rationale}


# האם נסגרה עסקה: הספק קיבל, או שהקונה קיבל הצעה של הספק
def is_deal(seller_status: str, decision: BuyerDecision | None) -> bool:
    """True if the supplier accepted or the buyer accepted a supplier option."""
    return seller_status == "accepted" or (decision is not None and decision.action == "accept")


# הסיבה שלא נסגרה עסקה, לפי סדר העדיפות
def no_deal_reason(seller: SellerProfile, buyer: BuyerTerms, seller_status: str, final: bool) -> str:
    """'delivery_impossible', 'seller_quit', 'max_rounds' or 'buyer_walk_away'."""
    if seller["min_days"] > max_allowed_days(buyer):
        return "delivery_impossible"
    if seller_status == "quit":
        return "seller_quit"
    if final:
        return "max_rounds"
    return "buyer_walk_away"
