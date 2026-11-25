"""Report prompt: the model phrases the meeting-prep report from ReportData only (spec section 7)."""

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from vbm.analysis import (REASON_HE, STYLE_HE, VARIANT_HE, concession_text, gap_lines, patience_text,
                          price_range_text)
from vbm.seller_sim import TERMS_HE

SYSTEM = """You write a short meeting-preparation report in Hebrew, in Markdown, for a business owner
who is about to meet a supplier. Use ONLY the data you are given; it is already in Hebrew.
Write only in Hebrew: never copy English words, codes or field names into the report.
Every number you write must appear in the data exactly as given; do not calculate new numbers, percentages or totals.
Terms: a "simulation" (סימולציה) is one full simulated negotiation; there are several simulations, one per
supplier style and buyer variant. A "round" (סבב) is one offer and answer inside a simulation.
Never mix the two words. Where the data gives a ready sentence, keep its meaning exactly.
Write exactly these sections, in this order, and no other section:
{sections}
End with one sentence saying that these are simulations, not a promise of the real supplier's behavior."""

SECTIONS = [
    "## האם אפשר לסגור עסקה - for each supplier style, based on the base variant.",
    "## טווח מחירים סביר - based on the price-range sentence.",
    "## על מה כדאי להתגמש - based on the concession sentence and the average price per variant.",
    "## מה מפוצץ את העסקה - based on the reasons for no deal and how many simulations each one ended.",
    "## כמה סבלנות נדרשת - based on the patience sentence.",
]
GAP_SECTION = ("## מה יסגור את הפער - what each option needs, which one closes the gap, and the caveat that "
               "these are the lowest offers observed and the supplier may go lower.")


# הצעה בעברית לנתוני הדוח
def _offer_he(item: dict) -> dict:
    return {"מחיר ליחידה": item["unit_price"], "מועד אספקה (ימים)": item["delivery_days"],
            "תנאי תשלום": TERMS_HE[item["payment_terms"]]}


# תצוגה עברית של ReportData למודל: בלי קודים באנגלית ובלי None
def report_view(data: dict) -> dict:
    """ReportData with Hebrew keys and values; numbers unchanged so the report check still applies."""
    buyer = data["buyer"]
    view = {
        "בקשת בעל העסק": {
            "מוצר": buyer["product"], "כמות": buyer["quantity"],
            "תקציב מקסימלי כולל": buyer["max_budget_total"], "תקציב ליחידה": buyer["budget_per_unit"],
            "יעד כולל": buyer["target_total"], "יעד ליחידה": buyer["target_per_unit"],
            "מועד אחרון (ימים)": buyer["deadline_days"], "מועד מועדף (ימים)": buyer["preferred_days"] or buyer["deadline_days"],
            "תנאי תשלום מועדפים": TERMS_HE[buyer["preferred_terms"]],
        },
        "מספר הסימולציות": data["simulations_count"],
        "מספר הסבבים המקסימלי בכל סימולציה": data["max_rounds"],
        "הסימולציות": [{
            "סגנון הספק": STYLE_HE[r["style"]], "גרסת הקונה": VARIANT_HE[r["variant"]],
            "תוצאה": "עסקה" if r["outcome"] == "deal" else "אין עסקה",
            **({"מחיר ליחידה": r["unit_price"], "מועד אספקה (ימים)": r["delivery_days"],
                "תנאי תשלום": TERMS_HE[r["payment_terms"]]} if r["outcome"] == "deal"
               else {"סיבה": REASON_HE[r["no_deal_reason"]]}),
            "מספר סבבים": r["rounds"],
            "ההצעה הנמוכה שנצפתה": r["lowest_offer"] if r["lowest_offer"] is not None else "לא נצפתה הצעה מתאימה",
        } for r in data["simulations"]],
        "עסקה בגרסת הבסיס לפי סגנון": {STYLE_HE[s]: "כן" if ok else "לא" for s, ok in data["feasibility"].items()},
        "משפט טווח המחירים": price_range_text(data["price_range"]),
        "מחיר ממוצע לפי גרסה": {VARIANT_HE[v]: m if m is not None else "אין עסקאות"
                                for v, m in data["variant_means"].items()},
        "משפט הוויתור המכריע": concession_text(data),
        "סיבות לאי-סגירה (מספר סימולציות)": {REASON_HE[k]: n for k, n in data["dealbreakers"].items()}
                                             or "בכל הסימולציות נסגרה עסקה",
        "משפט הסבלנות": patience_text(data),
    }
    gap = data["price_gap"]
    if gap["base_has_gap"]:
        view["פער המחיר"] = {
            "תקציב ליחידה": gap["budget_per_unit"],
            "לפי גרסה": {VARIANT_HE[v]: ({**_offer_he(item), "פער ליחידה מול התקציב": item["gap_per_unit"],
                                          "תקציב כולל שנדרש": item["required_total"],
                                          "סוגרת את הפער": "כן" if item["closes"] else "לא"}
                                         if item else "לא נצפתה הצעה מתאימה")
                         for v, item in gap["variants"].items()},
            "סיכום": gap_lines(gap),
        }
    return view


# בניית הפרומפט של הדוח מ-ReportData, ובניסיון חוזר גם המספרים שלא אומתו
def build_report_prompt(report_data: dict, unverified: list[str]) -> list[BaseMessage]:
    """Return the system and user messages for writing the report."""
    user = "הנתונים:\n" + json.dumps(report_view(report_data), ensure_ascii=False, indent=2)
    if unverified:
        user += ("\n\nYour previous report contained numbers that are not in the data: "
                 + ", ".join(unverified) + ". Write the report again without them.")
    sections = SECTIONS + ([GAP_SECTION] if report_data["price_gap"]["base_has_gap"] else [])
    return [SystemMessage(content=SYSTEM.format(sections="\n".join(sections))), HumanMessage(content=user)]
