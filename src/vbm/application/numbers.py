"""VBM number checks: every number in a text must come from known data (report check and message check)."""

import re

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
SMALL_NUMBERS = set(range(0, 11))


# כל המספרים בטקסט
def numbers_in_text(text: str) -> list[str]:
    """Number tokens in a text, as written."""
    return NUMBER_RE.findall(text)


# כל המספרים שמופיעים ב-ReportData, כולל בתוך מחרוזות
def numbers_in_data(value) -> set[float]:
    """Every number found anywhere in a nested structure."""
    found: set[float] = set()
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.add(float(value))
    elif isinstance(value, str):
        found.update(float(t.replace(",", "")) for t in numbers_in_text(value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in_data(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= numbers_in_data(item)
    return found


# המספרים בדוח שלא קיימים ב-ReportData
def unverified_numbers(text: str, report_data: dict) -> list[str]:
    """Numbers in the report that do not appear in ReportData (small counts 0-10 are allowed)."""
    allowed = numbers_in_data(report_data) | {float(n) for n in SMALL_NUMBERS}
    bad = []
    for token in numbers_in_text(text):
        value = float(token.replace(",", ""))
        if not any(abs(value - a) <= 0.01 for a in allowed) and token not in bad:
            bad.append(token)
    return bad
