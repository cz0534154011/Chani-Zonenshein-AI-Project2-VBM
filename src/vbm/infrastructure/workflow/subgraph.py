"""VBM subgraph: one negotiation between the buyer agent and one simulated supplier (spec section 5): thin nodes."""

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from vbm.adapters.texts import GUARDRAIL_RATIONALE, buyer_template_message, guardrail_feedback, offer_message, seller_message
from vbm.application import negotiation
from vbm.application.dto import BuyerDecision
from vbm.application.ports import BuyerDecider
from vbm.domain.economics import with_variant
from vbm.domain.schemas import SimResult, TranscriptEntry, validate_buyer_terms, validate_seller_profile
from vbm.domain.seller_sim import opening_offer, respond
from vbm.infrastructure.settings import PROMPT_VERSION
from vbm.infrastructure.wiring import default_buyer_decider
from vbm.infrastructure.workflow.state import NegotiationInput, NegotiationOutput, NegotiationState


# האם הקונה בתור האחרון (אחרי ההצעה האחרונה של הספק)
def is_final_turn(state: NegotiationState) -> bool:
    """True after the supplier's offer in the last round (P3)."""
    return negotiation.is_final_turn(state["round"], state["max_rounds"])


# מספר הסבב שבו נרשם תור הקונה בתמליל
def buyer_round(state: NegotiationState) -> int:
    """Round number for the buyer's current turn."""
    return negotiation.buyer_round(state["round"], state["max_rounds"])


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


# הקונה מחליט: הפרומפט נבנה רק מנתוני הקונה, מהתמליל וממשוב המעקה, לפי הגרסה שב-config
def make_buyer_decide(decider: BuyerDecider):
    """Return the buyer_decide node bound to the given buyer port."""
    def buyer_decide(state: NegotiationState, config: RunnableConfig) -> dict:
        """Call the buyer model and store its decision (None if the output was invalid)."""
        version = (config.get("configurable") or {}).get("prompt_version", PROMPT_VERSION)
        decision = decider.decide(state["buyer"], state["transcript"], state["guardrail_feedback"],
                                  buyer_round(state), state["max_rounds"], version)
        return {"pending_decision": decision}
    return buyer_decide


# המעקה: בודק את ההחלטה, מחזיר לתיקון, ואחרי 2 כישלונות מצמיד
def guardrail(state: NegotiationState) -> dict:
    """Validate the buyer decision; retry with feedback, or clamp after GUARDRAIL_MAX_RETRIES."""
    decision, final = state["pending_decision"], is_final_turn(state)
    review = negotiation.review_decision(state["buyer"], decision, state["seller_offers"], state["transcript"],
                                         final, state["max_rounds"], state["guardrail_retries"])
    counts = {"message_mismatch": state["message_mismatch"] + int(review["mismatch"])}

    if review["outcome"] == "pass":
        passed = decision.model_copy(update={"offer": review["offer"]})
        first = state["first_offer"] or passed.offer
        return {**counts, "pending_decision": passed, "guardrail_feedback": None, "guardrail_retries": 0,
                "first_offer": first, "transcript": [negotiation.buyer_entry(buyer_round(state), passed)]}

    counts["guardrail_hits"] = state["guardrail_hits"] + 1
    if review["outcome"] == "retry":
        return {**counts, "guardrail_feedback": guardrail_feedback(review["problems"]),
                "guardrail_retries": state["guardrail_retries"] + 1}

    if review["outcome"] == "force_walk_away":
        forced = BuyerDecision(action="walk_away", offer=None,
                               message=buyer_template_message(None), rationale=GUARDRAIL_RATIONALE)
        return {**counts, "pending_decision": forced, "guardrail_feedback": None, "guardrail_retries": 0}
    clamped = review["offer"]
    forced = BuyerDecision(action="counter", offer=clamped,
                           message=buyer_template_message(clamped), rationale=GUARDRAIL_RATIONALE)
    return {**counts, "pending_decision": forced, "guardrail_feedback": None, "guardrail_retries": 0,
            "first_offer": state["first_offer"] or clamped,
            "transcript": [negotiation.buyer_entry(buyer_round(state), forced)]}


# הספק המדומה מגיב להצעה הנגדית לפי הכללים הקבועים
def seller_respond(state: NegotiationState) -> dict:
    """Apply the supplier rules to the buyer's counter-offer and advance the round."""
    round_no = state["round"] + 1
    buyer_offer = state["pending_decision"].offer
    response = respond(state["seller"], buyer_offer, round_no, state["max_rounds"], state["low_offer_streak"])
    en, he = seller_message(response, buyer_offer, state["seller"], round_no, state["max_rounds"])
    entry: TranscriptEntry = {"round": round_no, "speaker": "seller", "offers": response["offers"],
                              "message": en, "message_he": he, "rationale": None}
    return {"round": round_no, "seller_offers": response["offers"], "seller_status": response["status"],
            "low_offer_streak": response["low_offer_streak"], "transcript": [entry]}


# סיכום המשא ומתן לתוצאה אחת (SimResult)
def finalize(state: NegotiationState) -> dict:
    """Build the SimResult: outcome, final offer, rounds, no-deal reason and counters."""
    decision = state["pending_decision"]
    transcript = list(state["transcript"])
    new_entries: list[TranscriptEntry] = []
    if decision is not None and decision.action == "walk_away":
        new_entries.append(negotiation.buyer_entry(buyer_round(state), decision))
    deal = negotiation.is_deal(state["seller_status"], decision)
    reason = None if deal else negotiation.no_deal_reason(state["seller"], state["buyer"], state["seller_status"],
                                                          is_final_turn(state))
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


# בניית תת-הגרף: צמתים, קשתות קבועות וקשתות מותנות; הקונה מוזרק (ברירת מחדל: OpenAI)
def build_subgraph(buyer_decider: BuyerDecider | None = None):
    """Compile the negotiation subgraph (no checkpointer: the parent graph or Studio provides one)."""
    builder = StateGraph(NegotiationState, input_schema=NegotiationInput, output_schema=NegotiationOutput)
    builder.add_node("seller_open", seller_open)
    builder.add_node("buyer_decide", make_buyer_decide(buyer_decider or default_buyer_decider()))
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
