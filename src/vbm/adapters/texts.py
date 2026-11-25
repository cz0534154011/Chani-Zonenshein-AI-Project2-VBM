"""VBM texts: every Hebrew and English sentence the system shows or sends, built from data (interface adapters)."""

from vbm.application.negotiation import Problem
from vbm.domain.schemas import Offer, SellerProfile
from vbm.domain.seller_sim import SellerResponse

TERMS_EN = {"advance": "payment in advance", "net30": "net 30", "net60": "net 60"}
TERMS_HE = {"advance": "תשלום מראש", "net30": "שוטף+30", "net60": "שוטף+60"}
STYLE_HE = {"tough": "קשוח", "balanced": "מאוזן", "flexible": "גמיש"}
VARIANT_HE = {"base": "בסיס", "payment": "גמישות בתשלום", "delivery": "גמישות במועד"}
REASON_HE = {
    "delivery_impossible": "המועד שנדרש מהיר מהמועד המינימלי של הספק",
    "seller_quit": "הספק פרש בגלל הצעות נמוכות מדי",
    "buyer_walk_away": "הקונה פרש",
    "max_rounds": "נגמרו הסבבים בלי הסכמה",
}
CONCESSION_HE = {"payment": "גמישות בתנאי התשלום", "delivery": "גמישות במועד האספקה", "none": "אין ויתור מכריע"}



# הודעת הספק בשתי שפות, מתוך תבנית: רק מספרי ההצעה, אף פעם לא הרצפה
def offer_message(offers: list[Offer], final: bool = False, note_en: str = "", note_he: str = "") -> tuple[str, str]:
    """Build the supplier's counter-offer text in English and Hebrew."""
    en = [f"{o.unit_price} per unit, delivery in {o.delivery_days} days, {TERMS_EN[o.payment_terms]}" for o in offers]
    he = [f"{o.unit_price} ליחידה, אספקה תוך {o.delivery_days} ימים, {TERMS_HE[o.payment_terms]}" for o in offers]
    text_en = "I can offer " + " or ".join(en) + "."
    text_he = "אני יכול להציע " + " או ".join(he) + "."
    if final:
        text_en = "This is my final offer. " + text_en
        text_he = "זו ההצעה האחרונה שלי. " + text_he
    if note_en:
        text_en = note_en + " " + text_en
        text_he = note_he + " " + text_he
    return text_en, text_he


# הודעת הספק לתגובה שלו, לפי הכלל שהופעל: רק מספרי ההצעה, אף פעם לא הרצפה
def seller_message(response: SellerResponse, buyer_offer: Offer, seller: SellerProfile, round_no: int,
                   max_rounds: int) -> tuple[str, str]:
    """English and Hebrew text of the supplier's response to buyer_offer in round round_no."""
    final = round_no >= max_rounds
    days, terms = buyer_offer.delivery_days, buyer_offer.payment_terms
    if response["reason"] == "delivery_below_min":
        note_en = f"Delivery in {days} days is not possible; the earliest I can deliver is {seller['min_days']} days."
        note_he = f"אספקה תוך {days} ימים אינה אפשרית; המועד המוקדם ביותר הוא {seller['min_days']} ימים."
        return offer_message(response["offers"], final, note_en, note_he)
    if response["status"] == "accepted":
        en = (f"Agreed: {buyer_offer.unit_price} per unit, delivery in {days} days, "
              f"{TERMS_EN[terms]}. We have a deal.")
        he = (f"מוסכם: {buyer_offer.unit_price} ליחידה, אספקה תוך {days} ימים, "
              f"{TERMS_HE[terms]}. יש עסקה.")
        return en, he
    if response["status"] == "quit":
        en = "Your offers are too far from anything I can accept. I am ending the negotiation."
        he = "ההצעות שלך רחוקות מדי ממה שאני יכול לקבל. אני מסיים את המשא ומתן."
        return en, he
    return offer_message(response["offers"], final)


# הודעת קונה מתבנית, כשהקוד מחליף את ההחלטה של המודל
def buyer_template_message(offer: Offer | None) -> str:
    """English buyer message for a code-made decision."""
    if offer is None:
        return "I cannot accept these terms. I am ending the negotiation."
    return (f"I can offer {offer.unit_price} per unit, delivery in {offer.delivery_days} days, "
            f"{TERMS_EN[offer.payment_terms]}.")


# משוב המעקה לקונה, באנגלית, לפי קודי הבעיות שהמעקה מצא
def guardrail_feedback(problems: list[Problem]) -> str:
    """English feedback for the buyer model, one sentence per problem, in the order found."""
    sentences = []
    for code, data in problems:
        if code == "invalid_output":
            sentences.append("Your output was not a valid decision.")
        elif code == "accept_unknown_option":
            sentences.append("To accept, give exactly one of the supplier's current options.")
        elif code == "counter_after_final":
            sentences.append("The supplier made a final offer: you can only accept or walk away.")
        elif code == "over_budget":
            sentences.append(f"Total {data['total']} exceeds your maximum budget {data['budget']}.")
        elif code == "late_delivery":
            sentences.append(f"Delivery in {data['days']} days is later than your limit of {data['limit']} days.")
        elif code == "payment_terms":
            sentences.append(f"Payment terms must be one of: {', '.join(data['allowed'])}.")
        elif code == "message_mismatch":
            sentences.append("The numbers in your message do not match your offer.")
        else:
            raise ValueError(f"unknown guardrail problem: {code}")
    return " ".join(sentences)


# הנימוק שנרשם כשהמעקה מחליט במקום הקונה
GUARDRAIL_RATIONALE = "Set by the guardrail after repeated invalid decisions."


# הודעות הפענוח בעצירה 1
PARSE_FAILED_NOTE = "לא הצלחתי לפענח את הבקשה. נא לנסח מחדש או להוסיף פרטים."


# הערה על נתונים שפוענחו ואינם תקינים
def invalid_terms_note(error: str) -> str:
    """Hebrew note for parsed terms that failed validation."""
    return f"הנתונים שפוענחו אינם תקינים: {error}"


# הבקשה המקורית עם התיקון של המשתמש, לפענוח מחדש
def corrected_request(raw_request: str, correction: str) -> str:
    """The request text with the user's correction appended."""
    return f"{raw_request}\nתיקון: {correction}"


# משפט הסבלנות בעברית, כולל המקרים שבהם אין נתון
def patience_text(data: dict) -> str:
    """Hebrew sentence on the tough supplier's patience, never leaving None to interpretation."""
    percent, max_rounds = data["patience_threshold_percent"], data["max_rounds"]
    if data["patience"] is not None:
        return (f"הספק הקשוח ירד לראשונה מתחת ל-{percent}% מהמחירון בסבב {data['patience']} "
                f"מתוך {max_rounds}. עד אז כדאי להחזיק בעמדה.")
    tough = [r for r in data["simulations"] if r["style"] == "tough" and r["variant"] == "base"]
    if not tough:
        return "לא נבדק ספק קשוח בסימולציות האלה, ולכן אין נתון על הסבלנות הנדרשת."
    if tough[0]["rounds"] < max_rounds:
        return (f"הסימולציה מול הספק הקשוח הסתיימה בסבב {tough[0]['rounds']}, לפני שהספק ירד מתחת ל-{percent}% "
                "מהמחירון, ולכן אין נתון על הסבלנות הנדרשת.")
    return (f"גם אחרי {max_rounds} סבבים הספק הקשוח לא ירד מתחת ל-{percent}% מהמחירון, "
            "כלומר מול ספק כזה נדרשת סבלנות רבה.")


# משפט טווח המחירים בעברית: מחיר אחד או טווח
def price_range_text(price_range: dict | None) -> str:
    """Hebrew sentence on the base-deal prices."""
    if not price_range:
        return "לא נסגרה אף עסקה בגרסת הבסיס."
    if price_range["min"] == price_range["max"]:
        return f"כל עסקאות הבסיס נסגרו ב-{price_range['min']} ליחידה."
    return f"עסקאות הבסיס נסגרו בין {price_range['min']} ל-{price_range['max']} ליחידה."


# משפט הוויתור המכריע בעברית, כולל הסיבה
def concession_text(data: dict) -> str:
    """Hebrew sentence saying which concession is decisive and why."""
    concession = data["decisive_concession"]
    if concession == "none":
        return "אף גמישות לא הפכה 'אין עסקה' לעסקה, ואף אחת לא הורידה את המחיר הממוצע ביותר מ-1%."
    deals = {v: {r["style"] for r in data["simulations"] if r["variant"] == v and r["outcome"] == "deal"}
             for v in ("base", concession)}
    converted = [s for s in ("tough", "balanced", "flexible") if s in deals[concession] - deals["base"]]
    if converted:
        count = "סימולציה אחת" if len(converted) == 1 else f"{len(converted)} סימולציות"
        names = ", ".join(STYLE_HE[s] for s in converted)
        return f"{CONCESSION_HE[concession]} הפכה {count} מ'אין עסקה' לעסקה (מול ספק {names})."
    means = data["variant_means"]
    return (f"{CONCESSION_HE[concession]} הורידה את המחיר הממוצע מ-{means['base']} "
            f"ל-{means[concession]} ליחידה.")


# שורות הפער בעברית: כמה חסר בבסיס ומה כל גמישות סוגרת; ריק אם אין פער
def gap_lines(gap: dict) -> list[str]:
    """Hebrew lines on the price gap (empty when the base variant has no gap)."""
    if not gap["base_has_gap"]:
        return []
    base = gap["variants"]["base"]
    lines = [f"בבסיס ההצעה הנמוכה שנצפתה היא {base['unit_price']} ליחידה, {base['gap_per_unit']} מעל התקציב "
             f"ליחידה ({gap['budget_per_unit']}). לסגירה בלי גמישות נדרש תקציב כולל של {base['required_total']}."]
    for variant in ("payment", "delivery"):
        item = gap["variants"][variant]
        if item is None:
            lines.append(f"{CONCESSION_HE[variant]}: לא נצפתה הצעה מתאימה.")
        elif item["closes"]:
            lines.append(f"{CONCESSION_HE[variant]}: סוגרת את הפער ({item['unit_price']} ליחידה).")
        else:
            lines.append(f"{CONCESSION_HE[variant]}: לא סוגרת את הפער (נשארים {item['gap_per_unit']} ליחידה).")
    return lines


# תקציר של 3-4 שורות לעצירה 2
def build_preview(data: dict) -> str:
    """Short Hebrew summary of the findings for the second stop (from ReportData)."""
    feasibility, price_range, concession = data["feasibility"], data["price_range"], data["decisive_concession"]
    dealbreakers, gap = data["dealbreakers"], data["price_gap"]
    deals = ", ".join(f"{STYLE_HE[s]}: {'כן' if ok else 'לא'}" for s, ok in feasibility.items())
    lines = [f"עסקה בגרסת הבסיס - {deals}."]
    lines.append(price_range_text(price_range))
    lines.append(f"הוויתור המכריע: {CONCESSION_HE[concession]}.")
    if dealbreakers:
        lines.append("מה מנע עסקה: " + "; ".join(f"{REASON_HE[k]} ({v})" for k, v in dealbreakers.items()) + ".")
    return "\n".join(lines + gap_lines(gap))


# דוח חלופי מתבנית, כשהמודל נכשל באימות 3 פעמים
def fallback_report(data: dict) -> str:
    """Hebrew Markdown report built in code from ReportData."""
    lines = ["> דוח חלופי: הדוח שנוסח במודל לא עבר את בדיקת המספרים, ולכן הדוח הזה הופק ישירות מהתוצאות.", ""]
    lines.append("## האם אפשר לסגור עסקה")
    for style, ok in data["feasibility"].items():
        lines.append(f"- ספק {STYLE_HE[style]}: {'נסגרה עסקה' if ok else 'לא נסגרה עסקה'} בגרסת הבסיס.")
    lines += ["", "## טווח מחירים סביר", f"- {price_range_text(data['price_range'])}"]
    lines += ["", "## על מה כדאי להתגמש", f"- {concession_text(data)}"]
    for variant, value in data["variant_means"].items():
        shown = value if value is not None else "אין עסקאות"
        lines.append(f"- מחיר ממוצע בגרסת {VARIANT_HE[variant]}: {shown}.")
    lines += ["", "## מה מפוצץ את העסקה"]
    if data["dealbreakers"]:
        lines += [f"- {REASON_HE[reason]}: {count}." for reason, count in data["dealbreakers"].items()]
    else:
        lines.append("- בכל הסימולציות נסגרה עסקה.")
    lines += ["", "## כמה סבלנות נדרשת", f"- {patience_text(data)}"]
    if data["price_gap"]["base_has_gap"]:
        lines += ["", "## מה יסגור את הפער"] + [f"- {line}" for line in gap_lines(data["price_gap"])]
        lines.append("- אלה ההצעות הנמוכות ביותר שנצפו. ייתכן שהספק היה מוכן לרדת עוד.")
    lines += ["", "התוצאות מבוססות על סימולציות, ואינן הבטחה להתנהגות הספק האמיתי."]
    return "\n".join(lines)
