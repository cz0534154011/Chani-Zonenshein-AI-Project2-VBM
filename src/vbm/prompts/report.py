"""Report prompt: the model phrases the meeting-prep report from ReportData only (spec section 7)."""

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM = """You write a short meeting-preparation report in Hebrew, in Markdown, for a business owner
who is about to meet a supplier. Use ONLY the data you are given. Every number you write must appear
in the data exactly as given; do not calculate new numbers, percentages or totals.
Seller styles: tough = קשוח, balanced = מאוזן, flexible = גמיש.
Buyer variants: base = בסיס, payment = גמישות בתנאי תשלום, delivery = גמישות במועד אספקה.
Sections, in this order:
## האם אפשר לסגור עסקה - for each seller style, based on the base variant.
## טווח מחירים סביר
## על מה כדאי להתגמש - based on decisive_concession and variant_means.
## מה מפוצץ את העסקה - based on dealbreakers.
## כמה סבלנות נדרשת - based on patience (the round where a tough supplier starts to concede).
State clearly that these are simulations, not a promise of the real supplier's behavior."""


# בניית הפרומפט של הדוח מ-ReportData, ובניסיון חוזר גם המספרים שלא אומתו
def build_report_prompt(report_data: dict, unverified: list[str]) -> list[BaseMessage]:
    """Return the system and user messages for writing the report."""
    data = {k: v for k, v in report_data.items() if k != "preview"}
    user = "Data:\n" + json.dumps(data, ensure_ascii=False, indent=2)
    if unverified:
        user += ("\n\nYour previous report contained numbers that are not in the data: "
                 + ", ".join(unverified) + ". Write the report again without them.")
    return [SystemMessage(content=SYSTEM), HumanMessage(content=user)]
