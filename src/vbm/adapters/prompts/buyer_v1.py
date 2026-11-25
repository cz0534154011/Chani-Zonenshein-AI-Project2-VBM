"""Buyer prompt v1 (spec section 10): built only from buyer terms, transcript and guardrail feedback."""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from vbm.adapters.texts import TERMS_EN
from vbm.domain.economics import allowed_payment_terms, max_allowed_days
from vbm.domain.schemas import BuyerTerms, TranscriptEntry


# בניית הפרומפט של הקונה מנתוני הקונה, מהתמליל וממשוב המעקה בלבד
def build_buyer_prompt(
    buyer: BuyerTerms, transcript: list[TranscriptEntry], guardrail_feedback: str | None
) -> list[BaseMessage]:
    """Return the system and user messages for one buyer turn."""
    terms = ", ".join(TERMS_EN[t] for t in allowed_payment_terms(buyer))
    system = (
        "You are a purchasing agent negotiating with a supplier. Get a good price and never exceed the budget.\n"
        f"Product: {buyer['product']}, quantity: {buyer['quantity']}.\n"
        f"Maximum budget (total): {buyer['max_budget_total']}. Target (total): {buyer['target_total']}.\n"
        f"Allowed payment terms: {terms}. Latest acceptable delivery: {max_allowed_days(buyer)} days.\n"
        "Prices in offers are per unit. Reply with action accept, counter or walk_away. "
        "For counter, give your offer. For accept, give the supplier option you accept. "
        "The message is what you say to the supplier; the rationale is private."
    )
    lines = []
    for entry in transcript:
        lines.append(f"Round {entry['round']}, {entry['speaker']}: {entry['message']}")
    user = "Conversation so far:\n" + "\n".join(lines)
    if guardrail_feedback:
        user += f"\n\nYour previous decision was rejected: {guardrail_feedback} Decide again."
    return [SystemMessage(content=system), HumanMessage(content=user)]
