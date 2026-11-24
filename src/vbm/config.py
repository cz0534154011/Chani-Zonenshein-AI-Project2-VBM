"""VBM configuration: fixed constants shared by the whole system."""

# מקדמי רצפת הספק לפי תנאי תשלום (אפיון 6.3)
PAYMENT_FACTORS: dict[str, float] = {
    "advance": 1.00,
    "net30": 1.01,
    "net60": 1.02,
}

# תוספת לרצפה כשהאספקה מהירה מהמועד הסטנדרטי של הספק (אפיון 6.3)
FAST_DELIVERY_FACTOR: float = 1.04

# מספר ספרות אחרי הנקודה בכל מחיר
PRICE_DECIMALS: int = 2

# מספר הסבבים המקסימלי במשא ומתן אחד (אפיון 6.4)
MAX_ROUNDS: int = 8

# קצב הוויתורים לפי סגנון הספק: ככל שגבוה יותר, הספק מוותר מאוחר יותר (אפיון 6.4)
BETA: dict[str, float] = {
    "tough": 3.0,
    "balanced": 1.0,
    "flexible": 0.5,
}

# כלל הפרישה: הצעה מתחת ל-60% מהרצפה, 3 פעמים ברצף (אפיון 6.5)
LOW_OFFER_RATIO: float = 0.6
LOW_OFFER_STREAK: int = 3

# טווחי ההגרלה של ספק מדומה (אפיון 6.2)
LIST_PRICE_FACTOR_RANGE: tuple[float, float] = (1.3, 1.9)   # x target price per unit
MIN_PRICE_FACTOR_RANGE: tuple[float, float] = (0.65, 0.90)  # x list price
STANDARD_DAYS_RANGE: tuple[int, int] = (14, 35)
MIN_DAYS_GAP_RANGE: tuple[int, int] = (3, 10)               # standard_days minus this
MIN_DAYS_FLOOR: int = 5

# טווח הסכמה "צר": רוחב הטווח קטן מ-8% מהתקרה (משחזר את התמהיל שבאפיון)
NARROW_ZOPA_RATIO: float = 0.08
