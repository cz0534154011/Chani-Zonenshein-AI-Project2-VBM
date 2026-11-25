"""VBM data structures (spec section 5.1)."""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, model_validator

PaymentTerms = Literal["advance", "net30", "net60"]
Variant = Literal["base", "payment", "delivery"]
Concession = Literal["payment", "delivery"]
SellerStyle = Literal["tough", "balanced", "flexible"]


class Offer(BaseModel):
    """One offer: price per unit, delivery time and payment terms."""

    unit_price: float = Field(gt=0)
    delivery_days: int = Field(gt=0)
    payment_terms: PaymentTerms


class BuyerDecision(BaseModel):
    """The buyer agent's decision in one round (LLM structured output)."""

    action: Literal["accept", "counter", "walk_away"] = Field(
        description="accept a supplier offer, counter with your own offer, or walk_away to end the negotiation")
    offer: Offer | None = Field(
        default=None, description="counter: your offer; accept: the supplier option you accept; walk_away: null")
    message: str = Field(description="what you say to the supplier, in English")
    rationale: str = Field(description="your private reasoning for this decision, one or two sentences; never empty")

    # הצעה נגדית חייבת לכלול הצעה
    @model_validator(mode="after")
    def _counter_requires_offer(self) -> "BuyerDecision":
        if self.action == "counter" and self.offer is None:
            raise ValueError("action 'counter' requires an offer")
        return self


class ParsedRequest(BaseModel):
    """The parser's reading of the free-text request (LLM structured output)."""

    product: str
    quantity: int
    max_budget_total: float
    target_total: float
    deadline_days: int
    preferred_days: int | None
    preferred_terms: PaymentTerms
    known_list_price: float | None
    known_standard_days: int | None
    notes: list[str]


class BuyerTerms(TypedDict):
    """The business owner's limits and preferences."""

    product: str
    quantity: int
    max_budget_total: float
    target_total: float
    deadline_days: int
    preferred_days: NotRequired[int]
    preferred_terms: PaymentTerms
    flexible_on: NotRequired[list[Concession]]


class SellerProfile(TypedDict):
    """The simulated supplier's secret limits."""

    list_price: float
    min_price: float
    standard_days: int
    min_days: int
    style: SellerStyle


# שורה אחת בתמליל המשא ומתן - רק מה שנאמר בפועל, בלי נתונים סודיים של הספק
class TranscriptEntry(TypedDict):
    round: int
    speaker: Literal["buyer", "seller"]
    offers: list[Offer]  # buyer: one offer or none; seller: one or two options
    message: str  # English, as said in the negotiation
    message_he: str | None  # seller only: Hebrew from the same template
    rationale: str | None  # buyer only: private reasoning, for display and trace


class SimResult(TypedDict):
    """The result of one simulated negotiation."""

    batch_id: int
    style: SellerStyle
    variant: Variant
    outcome: Literal["deal", "no_deal"]
    final: Offer | None
    rounds: int
    no_deal_reason: str | None
    guardrail_hits: int
    message_mismatch: int
    first_offer: Offer | None
    accepted_opening: bool
    transcript: list[TranscriptEntry]


# בדיקת תקינות של נתוני הקונה והשלמת ברירות מחדל
def validate_buyer_terms(buyer: BuyerTerms) -> BuyerTerms:
    """Return a checked copy of the buyer terms with defaults filled in."""
    checked: BuyerTerms = dict(buyer)  # type: ignore[assignment]
    checked.setdefault("preferred_days", checked["deadline_days"])
    checked.setdefault("flexible_on", [])

    if checked["quantity"] <= 0:
        raise ValueError("quantity must be positive")
    if checked["max_budget_total"] <= 0 or checked["target_total"] <= 0:
        raise ValueError("budget and target must be positive")
    if checked["target_total"] > checked["max_budget_total"]:
        raise ValueError("target_total cannot exceed max_budget_total")
    if checked["deadline_days"] <= 0 or checked["preferred_days"] <= 0:
        raise ValueError("delivery days must be positive")
    if checked["preferred_days"] > checked["deadline_days"]:
        raise ValueError("preferred_days cannot be later than deadline_days")
    if checked["preferred_terms"] not in ("advance", "net30", "net60"):
        raise ValueError(f"unknown payment terms: {checked['preferred_terms']}")
    for item in checked["flexible_on"]:
        if item not in ("payment", "delivery"):
            raise ValueError(f"unknown flexibility: {item}")
    return checked


# בדיקת תקינות של הפרופיל הסודי של הספק
def validate_seller_profile(seller: SellerProfile) -> SellerProfile:
    """Raise ValueError if the supplier's limits contradict each other."""
    if not 0 < seller["min_price"] <= seller["list_price"]:
        raise ValueError("need 0 < min_price <= list_price")
    if not 0 < seller["min_days"] <= seller["standard_days"]:
        raise ValueError("need 0 < min_days <= standard_days")
    if seller["style"] not in ("tough", "balanced", "flexible"):
        raise ValueError(f"unknown style: {seller['style']}")
    return seller
