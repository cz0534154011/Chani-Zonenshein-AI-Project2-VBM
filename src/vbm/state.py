"""VBM graph state: the shared data that graph nodes read and update."""

import operator
from typing import Annotated, Literal, TypedDict

from vbm.schemas import BuyerDecision, BuyerTerms, Offer, SellerProfile, SimResult, Variant


# שורה אחת בתמליל המשא ומתן - רק מה שנאמר בפועל, בלי נתונים סודיים
class TranscriptEntry(TypedDict):
    round: int
    speaker: Literal["buyer", "seller"]
    offer: Offer | None
    message: str


# ה-State של תת-הגרף: משא ומתן אחד בין קונה אחד לספק אחד
class NegotiationState(TypedDict):
    # fixed for the whole negotiation
    buyer: BuyerTerms
    seller: SellerProfile  # secret: never passed to the buyer prompt
    variant: Variant
    batch_id: int
    max_rounds: int
    # progress
    round: int
    seller_offers: list[Offer]  # latest supplier offer: one option, or two (seller terms / buyer terms)
    pending_decision: BuyerDecision | None
    seller_status: Literal["open", "accepted", "quit"]
    # counters
    guardrail_retries: int
    guardrail_hits: int
    message_mismatch: int
    low_offer_streak: int
    first_offer: Offer | None
    # append-only lists (reducer: operator.add)
    transcript: Annotated[list[TranscriptEntry], operator.add]
    sim_results: Annotated[list[SimResult], operator.add]


# ה-State של הגרף הראשי: מהבקשה החופשית ועד הדוח
class MainState(TypedDict):
    # input and parsing
    raw_request: str | None
    parse_notes: str | None
    terms_confirmed: bool
    buyer: BuyerTerms
    # supplier assumptions
    seller_known: dict
    seller_profiles: dict | None
    seed: int
    max_rounds: int
    # simulations
    batch_id: int
    sim_specs: list[dict]
    sim_results: Annotated[list[SimResult], operator.add]
    # analysis, user choice and report
    report_data: dict | None
    user_choice: dict | None
    report_text: str | None
    report_ok: bool
    report_attempts: int
    report_is_fallback: bool
