"""VBM subgraph: one negotiation between the buyer agent and one simulated supplier (spec section 5)."""

import math
import re

from langgraph.graph import END, START, StateGraph

from vbm.config import GUARDRAIL_MAX_RETRIES
from vbm.economics import allowed_payment_terms, max_allowed_days, round_price, with_variant
from vbm.llm import get_buyer_decider
from vbm.prompts.buyer_v1 import build_buyer_prompt
from vbm.schemas import (
    BuyerDecision, BuyerTerms, Offer, SimResult, TranscriptEntry, validate_buyer_terms, validate_seller_profile,
)
from vbm.seller_sim import TERMS_EN, offer_message, opening_offer, respond
from vbm.state import NegotiationInput, NegotiationOutput, NegotiationState

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


# האם הקונה בתור האחרון (אחרי ההצעה האחרונה של הספק)
def is_final_turn(state: NegotiationState) -> bool:
    """True after the supplier's offer in the last round (P3)."""
    return state["round"] >= state["max_rounds"]


# מספר הסבב שבו נרשם תור הקונה בתמליל
def buyer_round(state: NegotiationState) -> int:
    """Round number for the buyer's current turn."""
    return state["max_rounds"] if is_final_turn(state) else state["round"] + 1


# הפרות של הצעה מול הגבולות של הקונה בגרסה שלו
def offer_problems(buyer: BuyerTerms, offer: Offer) -> list[str]:
    """List the buyer limits that the offer breaks (empty list = valid)."""
    problems = []
    total = round_price(offer.unit_price * buyer["quantity"])
    if total > buyer["max_budget_total"]:
        problems.append(f"Total {total} exceeds your maximum budget {buyer['max_budget_total']}.")
    if offer.delivery_days > max_allowed_days(buyer):
        problems.append(f"Delivery in {offer.delivery_days} days is later than your limit of {max_allowed_days(buyer)} days.")
    allowed = allowed_payment_terms(buyer)
    if offer.payment_terms not in allowed:
        problems.append(f"Payment terms must be one of: {', '.join(allowed)}.")
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


# הודעת קונה מתבנית, כשהקוד מחליף את ההחלטה של המודל
def buyer_template_message(offer: Offer | None) -> str:
    """English buyer message for a code-made decision."""
    if offer is None:
        return "I cannot accept these terms. I am ending the negotiation."
    return (f"I can offer {offer.unit_price} per unit, delivery in {offer.delivery_days} days, "
            f"{TERMS_EN[offer.payment_terms]}.")


# שורת תמליל של הקונה
def buyer_entry(state: NegotiationState, decision: BuyerDecision) -> TranscriptEntry:
    """Transcript entry for a buyer decision that passed the guardrail."""
    return {"round": buyer_round(state), "speaker": "buyer",
            "offers": [decision.offer] if decision.offer else [],
            "message": decision.message, "message_he": None, "rationale": decision.rationale}


# הספק פותח בהצעת עוגן, ומאתחלים את כל המונים
def seller_open(state: NegotiationState) -> dict:
    """Check the inputs, apply the variant, and make the anchor offer (list price, standard days, advance)."""
    buyer = with_variant(validate_buyer_terms(state["buyer"]), state["variant"])
    seller = validate_seller_profile(state["seller"])
    opening = opening_offer(seller)
    en, he = offer_message([opening])
    entry: TranscriptEntry = {"round": 0, "speaker": "seller", "offers": [opening],
                              "message": en, "message_he": he, "rationale": None}
    return {"buyer": buyer, "seller": seller, "round": 0, "seller_offers": [opening], "pending_decision": None,
            "seller_status": "open", "guardrail_feedback": None, "guardrail_retries": 0,
            "guardrail_hits": 0, "message_mismatch": 0, "low_offer_streak": 0,
            "first_offer": None, "transcript": [entry]}


# הקונה מחליט: הפרומפט נבנה רק מנתוני הקונה, מהתמליל וממשוב המעקה
def buyer_decide(state: NegotiationState) -> dict:
    """Call the buyer model and store its decision (None if the output was invalid)."""
    messages = build_buyer_prompt(state["buyer"], state["transcript"], state["guardrail_feedback"])
    return {"pending_decision": get_buyer_decider().invoke(messages)}


# המעקה: בודק את ההחלטה, מחזיר לתיקון, ואחרי 2 כישלונות מצמיד
def guardrail(state: NegotiationState) -> dict:
    """Validate the buyer decision; retry with feedback, or clamp after GUARDRAIL_MAX_RETRIES."""
    buyer, decision, final = state["buyer"], state["pending_decision"], is_final_turn(state)
    problems: list[str] = []
    checked = decision.offer if decision else None
    if decision is None:
        problems.append("Your output was not a valid decision.")
    elif decision.action == "accept":
        checked = match_seller_offer(decision.offer, state["seller_offers"])
        if checked is None:
            problems.append("To accept, give exactly one of the supplier's current options.")
        else:
            problems += offer_problems(buyer, checked)
    elif decision.action == "counter":
        if final:
            problems.append("The supplier made a final offer: you can only accept or walk away.")
        else:
            problems += offer_problems(buyer, checked)
    mismatch = (decision is not None and checked is not None
                and has_message_mismatch(decision.message, checked, buyer, state["transcript"], state["max_rounds"]))
    if mismatch:
        problems.append("The numbers in your message do not match your offer.")
    counts = {"message_mismatch": state["message_mismatch"] + int(mismatch)}

    if not problems:
        passed = decision.model_copy(update={"offer": checked})
        first = state["first_offer"] or passed.offer
        return {**counts, "pending_decision": passed, "guardrail_feedback": None, "guardrail_retries": 0,
                "first_offer": first, "transcript": [buyer_entry(state, passed)]}

    counts["guardrail_hits"] = state["guardrail_hits"] + 1
    if state["guardrail_retries"] < GUARDRAIL_MAX_RETRIES:
        return {**counts, "guardrail_feedback": " ".join(problems),
                "guardrail_retries": state["guardrail_retries"] + 1}

    rationale = "Set by the guardrail after repeated invalid decisions."
    if final:
        forced = BuyerDecision(action="walk_away", offer=None,
                               message=buyer_template_message(None), rationale=rationale)
        return {**counts, "pending_decision": forced, "guardrail_feedback": None, "guardrail_retries": 0}
    base = checked or state["seller_offers"][0]
    clamped = clamp_offer(buyer, base)
    forced = BuyerDecision(action="counter", offer=clamped,
                           message=buyer_template_message(clamped), rationale=rationale)
    return {**counts, "pending_decision": forced, "guardrail_feedback": None, "guardrail_retries": 0,
            "first_offer": state["first_offer"] or clamped, "transcript": [buyer_entry(state, forced)]}


# הספק המדומה מגיב להצעה הנגדית לפי הכללים הקבועים
def seller_respond(state: NegotiationState) -> dict:
    """Apply the supplier rules to the buyer's counter-offer and advance the round."""
    round_no = state["round"] + 1
    response = respond(state["seller"], state["pending_decision"].offer, round_no,
                       state["max_rounds"], state["low_offer_streak"])
    entry: TranscriptEntry = {"round": round_no, "speaker": "seller", "offers": response["offers"],
                              "message": response["message_en"], "message_he": response["message_he"],
                              "rationale": None}
    return {"round": round_no, "seller_offers": response["offers"], "seller_status": response["status"],
            "low_offer_streak": response["low_offer_streak"], "transcript": [entry]}


# סיכום המשא ומתן לתוצאה אחת (SimResult)
def finalize(state: NegotiationState) -> dict:
    """Build the SimResult: outcome, final offer, rounds, no-deal reason and counters."""
    decision = state["pending_decision"]
    transcript = list(state["transcript"])
    new_entries: list[TranscriptEntry] = []
    if decision is not None and decision.action == "walk_away":
        new_entries.append(buyer_entry(state, decision))
    deal = state["seller_status"] == "accepted" or (decision is not None and decision.action == "accept")
    reason = None
    if not deal:
        if state["seller"]["min_days"] > max_allowed_days(state["buyer"]):
            reason = "delivery_impossible"
        elif state["seller_status"] == "quit":
            reason = "seller_quit"
        elif is_final_turn(state):
            reason = "max_rounds"
        else:
            reason = "buyer_walk_away"
    result: SimResult = {
        "batch_id": state["batch_id"], "style": state["seller"]["style"], "variant": state["variant"],
        "outcome": "deal" if deal else "no_deal", "final": decision.offer if deal else None,
        "rounds": state["round"], "no_deal_reason": reason,
        "guardrail_hits": state["guardrail_hits"], "message_mismatch": state["message_mismatch"],
        "first_offer": state["first_offer"], "accepted_opening": deal and state["round"] == 0,
        "transcript": transcript + new_entries,
    }
    return {"transcript": new_entries, "sim_results": [result]}


# אחרי הקונה: פרישה מסיימת; קבלה והצעה נגדית עוברות במעקה
def route_after_buyer(state: NegotiationState) -> str:
    """'finalize' on walk_away, otherwise 'guardrail'."""
    decision = state["pending_decision"]
    if decision is not None and decision.action == "walk_away":
        return "finalize"
    return "guardrail"


# אחרי המעקה: חזרה לתיקון, לספק, או לסיום
def route_after_guardrail(state: NegotiationState) -> str:
    """'buyer_decide' to retry, 'seller_respond' for a counter, 'finalize' for accept or walk_away."""
    if state["guardrail_feedback"] is not None:
        return "buyer_decide"
    if state["pending_decision"].action == "counter":
        return "seller_respond"
    return "finalize"


# אחרי הספק: קבלה או פרישה מסיימות; אחרת תור הקונה (כולל התור האחרון)
def route_after_seller(state: NegotiationState) -> str:
    """'finalize' if the supplier accepted or quit, otherwise 'buyer_decide' (loop)."""
    if state["seller_status"] in ("accepted", "quit"):
        return "finalize"
    return "buyer_decide"


# בניית תת-הגרף: צמתים, קשתות קבועות וקשתות מותנות
def build_subgraph():
    """Compile the negotiation subgraph (no checkpointer: the parent graph or Studio provides one)."""
    builder = StateGraph(NegotiationState, input_schema=NegotiationInput, output_schema=NegotiationOutput)
    builder.add_node("seller_open", seller_open)
    builder.add_node("buyer_decide", buyer_decide)
    builder.add_node("guardrail", guardrail)
    builder.add_node("seller_respond", seller_respond)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "seller_open")
    builder.add_edge("seller_open", "buyer_decide")
    builder.add_conditional_edges("buyer_decide", route_after_buyer, ["guardrail", "finalize"])
    builder.add_conditional_edges("guardrail", route_after_guardrail, ["buyer_decide", "seller_respond", "finalize"])
    builder.add_conditional_edges("seller_respond", route_after_seller, ["buyer_decide", "finalize"])
    builder.add_edge("finalize", END)
    return builder.compile()


subgraph = build_subgraph()
