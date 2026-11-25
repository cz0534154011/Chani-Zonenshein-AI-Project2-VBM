"""Buyer prompt v2 (spec section 10): explicit strategy plus round, history and an allowed offer range, from buyer data only."""

import math

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from vbm.economics import allowed_payment_terms, max_allowed_days, round_price
from vbm.schemas import BuyerTerms, TranscriptEntry
from vbm.seller_sim import TERMS_EN

# חלק הפער הנותר שמותר לוותר עליו בסבב אחד, וגבול תחתון להצעת הפתיחה (x היעד ליחידה)
MAX_CONCESSION_SHARE = 0.25
OPENING_FLOOR_SHARE = 0.9


# התקרה ליחידה, מעוגלת כלפי מטה כמו במעקה
def ceiling_per_unit(buyer: BuyerTerms) -> float:
    """Maximum budget per unit, rounded down to cents."""
    return math.floor(buyer["max_budget_total"] / buyer["quantity"] * 100) / 100


# ההצעות הקודמות של הקונה (מחיר ליחידה), לפי הסדר
def previous_buyer_prices(transcript: list[TranscriptEntry]) -> list[float]:
    """Unit prices of the buyer's earlier offers in the transcript."""
    return [entry["offers"][0].unit_price for entry in transcript if entry["speaker"] == "buyer" and entry["offers"]]


# טווח ההצעה המותר בסבב: פתיחה ביעד או מתחתיו, ואחר כך לכל היותר רבע מהפער הנותר
def offer_range(buyer: BuyerTerms, transcript: list[TranscriptEntry]) -> tuple[float, float]:
    """(lowest, highest) unit price the buyer should offer this round."""
    target = round_price(buyer["target_total"] / buyer["quantity"])
    previous = previous_buyer_prices(transcript)
    if not previous:
        return round_price(target * OPENING_FLOOR_SHARE), target
    last = previous[-1]
    latest = [entry for entry in transcript if entry["speaker"] == "seller"][-1]["offers"]
    ask = min([o.unit_price for o in latest] + [ceiling_per_unit(buyer)])
    if ask <= last:
        return last, last
    return last, round_price(last + MAX_CONCESSION_SHARE * (ask - last))


# בניית הפרומפט של הקונה v2 מנתוני הקונה, מהתמליל, ממשוב המעקה וממספר הסבב בלבד
def build_buyer_prompt(
    buyer: BuyerTerms, transcript: list[TranscriptEntry], guardrail_feedback: str | None, round_no: int, max_rounds: int
) -> list[BaseMessage]:
    """Return the system and user messages for one buyer turn."""
    terms = ", ".join(TERMS_EN[t] for t in allowed_payment_terms(buyer))
    target = round_price(buyer["target_total"] / buyer["quantity"])
    ceiling = ceiling_per_unit(buyer)
    system = (
        "You are a purchasing agent negotiating with a supplier. Your goal is the lowest price you can get, "
        "never above the maximum budget.\n"
        f"Product: {buyer['product']}, quantity: {buyer['quantity']}.\n"
        f"Maximum budget (total): {buyer['max_budget_total']}, that is {ceiling} per unit. "
        f"Target (total): {buyer['target_total']}, that is {target} per unit.\n"
        f"Allowed payment terms: {terms}. Latest acceptable delivery: {max_allowed_days(buyer)} days.\n"
        "Strategy:\n"
        "1. Open at or below your target price per unit.\n"
        "2. Make each concession smaller than your previous one, and never more than a quarter of the remaining gap "
        "between your last offer and the supplier's current price.\n"
        "3. Never accept the supplier's opening offer.\n"
        "4. Concede first on payment terms or delivery (only within what is allowed above), and only then on price.\n"
        "5. The maximum budget is a hard ceiling, not an offer. "
        "Never offer the maximum budget itself except in the final round.\n"
        "6. Walk away only if the supplier will not go below your ceiling and fewer than two rounds remain.\n"
        "Prices in offers are per unit. Reply with action accept, counter or walk_away. "
        "For counter, give your offer. For accept, give the supplier option you accept. "
        "The message is what you say to the supplier; the rationale is private."
    )
    lines = [f"Round {entry['round']}, {entry['speaker']}: {entry['message']}" for entry in transcript]
    previous = previous_buyer_prices(transcript)
    low, high = offer_range(buyer, transcript)
    user = "Conversation so far:\n" + "\n".join(lines)
    user += f"\n\nThis is round {round_no} of {max_rounds}; rounds left after this one: {max_rounds - round_no}."
    user += f"\nYour previous offers (per unit): {', '.join(map(str, previous)) if previous else 'none yet'}."
    if round_no >= max_rounds:
        user += "\nThe supplier's offer is final: you can only accept or walk away."
    else:
        user += f"\nAllowed offer range this round (per unit): {low} to {high}."
    if guardrail_feedback:
        user += f"\n\nYour previous decision was rejected: {guardrail_feedback} Decide again."
    return [SystemMessage(content=system), HumanMessage(content=user)]
