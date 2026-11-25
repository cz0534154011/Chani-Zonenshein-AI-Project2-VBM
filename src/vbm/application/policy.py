"""VBM process policy: retry limits of the guardrail and the report check (application layer)."""

# המעקה: מספר הניסיונות החוזרים של הקונה לפני שהקוד מצמיד את ההצעה (S4)
GUARDRAIL_MAX_RETRIES: int = 2

# אימות הדוח: מספר הכתיבות המקסימלי לפני דוח חלופי (סעיף 3.4)
MAX_REPORT_ATTEMPTS: int = 3
