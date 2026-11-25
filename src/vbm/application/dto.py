"""VBM port results: the buyer's decision and the parsed request, as the language-model ports return them."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from vbm.domain.schemas import Offer, PaymentTerms


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
