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

# המעקה: מספר הניסיונות החוזרים של הקונה לפני שהקוד מצמיד את ההצעה (S4)
GUARDRAIL_MAX_RETRIES: int = 2

# מודל לכל תפקיד (אפיון 13); בחירה סופית במשימה 0.2
MODELS: dict[str, str] = {
    "parser": "gpt-4o-mini",
    "buyer": "gpt-4o-mini",
    "report": "gpt-4o-mini",
    "translate": "gpt-4o-mini",
}

# temperature לכל תפקיד: הקונה מגוון, הפענוח והדוח עקביים (ה6)
TEMPERATURES: dict[str, float] = {
    "parser": 0.0,
    "buyer": 0.7,
    "report": 0.0,
    "translate": 0.0,
}

# ניתוח: ויתור מכריע רק אם שיפר את המחיר הממוצע ביותר מ-1% (אפיון 7)
DECISIVE_MIN_IMPROVEMENT: float = 0.01

# סבלנות: הסבב הראשון שבו ספק קשוח ירד מתחת ל-90% מהמחירון (אפיון 7)
PATIENCE_RATIO: float = 0.9

# אימות הדוח: מספר הכתיבות המקסימלי לפני דוח חלופי (סעיף 3.4)
MAX_REPORT_ATTEMPTS: int = 3

# דאטהסט: מוצרים קבועים (מוצר, כמות, מחיר יעד ליחידה) וטווחי ההגרלה של הקונה (שלב 8)
DATASET_PRODUCTS: tuple[tuple[str, int, float], ...] = (
    ("office chair", 500, 320.0),
    ("laptop", 40, 3500.0),
    ("printer paper box", 1000, 25.0),
    ("office desk", 120, 900.0),
    ("LED lamp", 300, 60.0),
)
DATASET_BUDGET_FACTOR_RANGE: tuple[float, float] = (1.1, 1.4)  # x target total
DATASET_DEADLINE_RANGE: tuple[int, int] = (14, 45)
DATASET_PREFERRED_GAP_RANGE: tuple[int, int] = (0, 10)          # deadline minus this
DATASET_QUOTAS: dict[str, int] = {"wide": 6, "narrow": 5, "no_zopa_price": 4, "no_zopa_delivery": 3}
DATASET_NAME: str = "vbm-meeting-prep-18"

# ניסויים בשלב 9: חזרות לכל תרחיש, ותרחישים שרצים במקביל (כל אחד מריץ 9 סימולציות)
EXPERIMENT_REPETITIONS: int = 2
EXPERIMENT_MAX_CONCURRENCY: int = 2
DATASET_CATEGORY_ORDER: tuple[str, ...] = ("wide", "narrow", "no_zopa_price", "no_zopa_delivery")

# גרסת הפרומפט של הקונה: ברירת המחדל, והגרסאות שאפשר לבחור ב-config["configurable"]["prompt_version"]
PROMPT_VERSION: str = "v1"
PROMPT_VERSIONS: tuple[str, ...] = ("v1", "v2")
