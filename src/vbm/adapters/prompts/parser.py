"""Parser prompt: free-text purchase request (usually Hebrew) -> ParsedRequest."""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM = """You turn a business owner's purchase request into structured data.
The request is usually in Hebrew. Read every number carefully ("210 אלף" = 210000).
Fields:
- product, quantity.
- max_budget_total: the most the owner can pay for the whole order. If given per unit, multiply by the quantity.
- target_total: the total the owner hopes to pay. If given per unit, multiply by the quantity.
- deadline_days: the latest acceptable delivery, in days from now.
- preferred_days: an earlier delivery the owner would prefer, or null if none was mentioned.
- preferred_terms: advance, net30 or net60 ("שוטף+30" = net30, "שוטף+60" = net60, "מראש" = advance).
- known_list_price, known_standard_days: what the owner already knows about the supplier, or null.
- notes: every assumption you made, each as one short sentence in Hebrew. If nothing was assumed, an empty list.
If a required value is missing, choose a reasonable value and write the assumption in notes."""


# בניית הפרומפט של המפענח מהבקשה החופשית בלבד
def build_parser_prompt(raw_request: str) -> list[BaseMessage]:
    """Return the system and user messages for parsing one request."""
    return [SystemMessage(content=SYSTEM), HumanMessage(content=raw_request)]
