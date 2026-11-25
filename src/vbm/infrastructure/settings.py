"""VBM settings: models, dataset and experiment parameters, default prompt version (infrastructure layer)."""

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

# גרסת הפרומפט של הקונה שבברירת המחדל; אפשר לבחור אחרת ב-config["configurable"]["prompt_version"]
PROMPT_VERSION: str = "v2"
