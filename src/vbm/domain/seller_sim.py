"""VBM simulated supplier: fixed, deterministic decision rules (spec section 6)."""

from typing import Literal, TypedDict

from vbm.domain.economics import round_price, seller_floor
from vbm.domain.rules import BETA, FAST_DELIVERY_FACTOR, LOW_OFFER_RATIO, LOW_OFFER_STREAK, PAYMENT_FACTORS
from vbm.domain.schemas import Offer, PaymentTerms, SellerProfile


class SellerResponse(TypedDict):
    status: Literal["open", "accepted", "quit"]
    offers: list[Offer]
    low_offer_streak: int
    reason: str | None


# הדרישה של הספק בסבב t, בתנאים שלו (תשלום מראש, מועד סטנדרטי)
def ask_price(seller: SellerProfile, round_no: int, max_rounds: int) -> float:
    """Concession curve: list - (list - min) * (t / T) ** beta."""
    t = min(max(round_no, 0), max_rounds)
    beta = BETA[seller["style"]]
    gap = seller["list_price"] - seller["min_price"]
    return round_price(seller["list_price"] - gap * (t / max_rounds) ** beta)


# הדרישה מותאמת לתנאים שהקונה ביקש; None אם המועד בלתי אפשרי
def required_price(
    seller: SellerProfile, ask: float, payment_terms: PaymentTerms, delivery_days: int
) -> float | None:
    """Current ask adjusted for the buyer's payment terms and delivery time."""
    if delivery_days < seller["min_days"]:
        return None
    price = ask * PAYMENT_FACTORS[payment_terms]
    if delivery_days < seller["standard_days"]:
        price *= FAST_DELIVERY_FACTOR
    return round_price(price)


# הצעת העוגן שפותחת את המשא ומתן
def opening_offer(seller: SellerProfile) -> Offer:
    """List price, standard delivery, payment in advance."""
    return Offer(
        unit_price=seller["list_price"],
        delivery_days=seller["standard_days"],
        payment_terms="advance",
    )


# הצעה נגדית: אפשרות אחת, או שתיים כשהקונה ביקש תנאי שעולה לספק
def counter_offers(
    seller: SellerProfile, ask: float, payment_terms: PaymentTerms, delivery_days: int
) -> list[Offer]:
    """Seller-terms option, plus a buyer-terms option when the buyer asked for costly terms."""
    costly = payment_terms != "advance" or delivery_days < seller["standard_days"]
    if not costly:
        return [Offer(unit_price=ask, delivery_days=delivery_days, payment_terms="advance")]
    own = Offer(unit_price=ask, delivery_days=seller["standard_days"], payment_terms="advance")
    theirs = Offer(
        unit_price=required_price(seller, ask, payment_terms, delivery_days),
        delivery_days=delivery_days,
        payment_terms=payment_terms,
    )
    return [own, theirs]


# תגובת הספק להצעת הקונה, לפי ארבעת הכללים ובסדר הזה (אפיון 6.5)
def respond(
    seller: SellerProfile,
    buyer_offer: Offer,
    round_no: int,
    max_rounds: int,
    low_offer_streak: int,
) -> SellerResponse:
    """Apply the four decision rules in order and return the supplier's response (data only; the text is built in adapters)."""
    ask = ask_price(seller, round_no, max_rounds)
    terms = buyer_offer.payment_terms
    days = buyer_offer.delivery_days

    # Rule 1: delivery faster than the supplier's minimum is impossible
    if days < seller["min_days"]:
        offers = counter_offers(seller, ask, terms, seller["min_days"])
        return {"status": "open", "offers": offers, "low_offer_streak": low_offer_streak,
                "reason": "delivery_below_min"}

    # Rule 2: the offer meets the current ask for the requested terms
    needed = required_price(seller, ask, terms, days)
    if buyer_offer.unit_price >= needed:
        return {"status": "accepted", "offers": [buyer_offer], "low_offer_streak": 0, "reason": None}

    # Rule 3: three offers in a row below 60% of the floor -> walk away
    floor = seller_floor(seller, terms, days)
    streak = low_offer_streak + 1 if buyer_offer.unit_price < LOW_OFFER_RATIO * floor else 0
    if streak >= LOW_OFFER_STREAK:
        return {"status": "quit", "offers": [], "low_offer_streak": streak, "reason": "low_offers"}

    # Rule 4: counter at the current ask
    offers = counter_offers(seller, ask, terms, days)
    return {"status": "open", "offers": offers, "low_offer_streak": streak, "reason": None}
