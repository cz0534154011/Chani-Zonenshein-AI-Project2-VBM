"""VBM economics: supplier floors and the zone of possible agreement (ZOPA)."""

from typing import Literal, TypedDict

from vbm.domain.rules import FAST_DELIVERY_FACTOR, NARROW_ZOPA_RATIO, PAYMENT_FACTORS, PRICE_DECIMALS
from vbm.domain.schemas import BuyerTerms, PaymentTerms, SellerProfile, Variant


class Zopa(TypedDict):
    zopa_low: float | None
    zopa_high: float
    zopa_exists: bool


# עיגול אחיד של כל מחיר במערכת
def round_price(value: float) -> float:
    """Round a price to PRICE_DECIMALS places."""
    return round(value, PRICE_DECIMALS)


# הרצפה של הספק לתנאים נתונים; None אם המועד בלתי אפשרי
def seller_floor(
    seller: SellerProfile, payment_terms: PaymentTerms, delivery_days: int
) -> float | None:
    """Lowest unit price the supplier accepts for these terms, or None if impossible."""
    if delivery_days < seller["min_days"]:
        return None
    floor = seller["min_price"] * PAYMENT_FACTORS[payment_terms]
    if delivery_days < seller["standard_days"]:
        floor *= FAST_DELIVERY_FACTOR
    return round_price(floor)


# זיהוי הגרסה של הקונה לפי flexible_on
def variant_of(buyer: BuyerTerms) -> Variant:
    """Return 'base', 'payment' or 'delivery' according to buyer['flexible_on']."""
    flexible = buyer.get("flexible_on", [])
    if "payment" in flexible:
        return "payment"
    if "delivery" in flexible:
        return "delivery"
    return "base"


# יצירת עותק של הקונה בגרסה מסוימת
def with_variant(buyer: BuyerTerms, variant: Variant) -> BuyerTerms:
    """Return a copy of the buyer terms set to the given variant."""
    copy: BuyerTerms = dict(buyer)  # type: ignore[assignment]
    copy["flexible_on"] = [] if variant == "base" else [variant]
    return copy


# תנאי התשלום שהקונה רשאי להציע בגרסה שלו
def allowed_payment_terms(buyer: BuyerTerms) -> list[PaymentTerms]:
    """Payment terms the buyer may offer in its variant."""
    if variant_of(buyer) == "payment":
        return ["advance", "net30", "net60"]
    return [buyer["preferred_terms"]]


# המועד המאוחר ביותר שהקונה רשאי לקבל בגרסה שלו
def max_allowed_days(buyer: BuyerTerms) -> int:
    """Latest delivery the buyer may accept in its variant (never beyond the deadline)."""
    if variant_of(buyer) == "delivery":
        return buyer["deadline_days"]
    return buyer.get("preferred_days", buyer["deadline_days"])


# חישוב טווח ההסכמה בין הקונה לספק
def compute_zopa(buyer: BuyerTerms, seller: SellerProfile) -> Zopa:
    """Compute zopa_low, zopa_high and zopa_exists for the buyer's variant."""
    days = max_allowed_days(buyer)
    floors = [seller_floor(seller, terms, days) for terms in allowed_payment_terms(buyer)]
    possible = [f for f in floors if f is not None]
    zopa_low = min(possible) if possible else None
    zopa_high = round_price(buyer["max_budget_total"] / buyer["quantity"])
    zopa_exists = zopa_low is not None and zopa_low <= zopa_high
    return {"zopa_low": zopa_low, "zopa_high": zopa_high, "zopa_exists": zopa_exists}


ZopaCategory = Literal["wide", "narrow", "no_zopa_price", "no_zopa_delivery"]


# סיווג טווח ההסכמה: רחב / צר / אין טווח במחיר / אין טווח במועד
def classify_zopa(zopa: Zopa) -> ZopaCategory:
    """Classify a ZOPA into one of the four dataset categories."""
    if zopa["zopa_low"] is None:
        return "no_zopa_delivery"
    if not zopa["zopa_exists"]:
        return "no_zopa_price"
    width = zopa["zopa_high"] - zopa["zopa_low"]
    return "narrow" if width < NARROW_ZOPA_RATIO * zopa["zopa_high"] else "wide"
