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
