"""VBM display helpers shared by the CLI and the Streamlit app (Hebrew labels, results and transcripts)."""

from vbm.adapters.texts import REASON_HE, STYLE_HE, TERMS_HE, VARIANT_HE
from vbm.application.ports import Translator

BUYER_LABELS = {
    "product": "מוצר", "quantity": "כמות", "max_budget_total": "תקציב מקסימלי (סך הכל)",
    "target_total": "יעד (סך הכל)", "deadline_days": "מועד אחרון (ימים)",
    "preferred_days": "מועד מועדף (ימים)", "preferred_terms": "תנאי תשלום מועדפים",
}
SELLER_LABELS = {"list_price": "מחירון", "min_price": "מחיר מינימום", "standard_days": "זמן אספקה רגיל (ימים)",
                 "min_days": "זמן אספקה מינימלי (ימים)"}


# הצעה בעברית
def offer_he(offer) -> str:
    """One offer as Hebrew text."""
    return f"{offer.unit_price} ליחידה, {offer.delivery_days} ימים, {TERMS_HE[offer.payment_terms]}"


# תווית של סימולציה: סגנון הספק וגרסת הקונה
def sim_label(result: dict) -> str:
    """'[style | variant]' in Hebrew."""
    return f"[{STYLE_HE[result['style']]} | {VARIANT_HE[result['variant']]}]"


# תיאור התוצאה של סימולציה בעברית
def outcome_he(result: dict) -> str:
    """Deal terms, or 'no deal' with the reason."""
    if result["final"]:
        return f"עסקה: {offer_he(result['final'])}"
    return f"אין עסקה: {REASON_HE[result['no_deal_reason']]}"


# שורת תוצאה אחת לסימולציה שהסתיימה
def result_line(result: dict) -> str:
    """'[style | variant] outcome (N rounds)'."""
    return f"{sim_label(result)} {outcome_he(result)} ({result['rounds']} סבבים)"


# התמליל של סימולציה בעברית: הספק מהתבנית, הקונה מתורגם, כולל הנימוק
def transcript_he(result: dict, translator: Translator) -> list[dict]:
    """Rows of {round, speaker, text, rationale} in Hebrew for one simulation; buyer lines go through translator."""
    buyer_entries = [e for e in result["transcript"] if e["speaker"] == "buyer"]
    texts = []
    for e in buyer_entries:
        texts += [e["message"], e["rationale"] or "-"]
    translated = iter(translator.translate(texts)) if texts else iter([])
    rows = []
    for e in result["transcript"]:
        if e["speaker"] == "seller":
            rows.append({"round": e["round"], "speaker": "הספק", "text": e["message_he"], "rationale": None})
        else:
            rows.append({"round": e["round"], "speaker": "הקונה", "text": next(translated),
                         "rationale": next(translated)})
    return rows
