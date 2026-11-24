"""VBM language models: one chat model per role, created only when first needed."""

from functools import lru_cache

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from vbm.config import MODELS, TEMPERATURES
from vbm.schemas import BuyerDecision, ParsedRequest


# מודל השפה של תפקיד מסוים, לפי config; נוצר פעם אחת בלבד
@lru_cache(maxsize=None)
def get_chat_model(role: str) -> ChatOpenAI:
    """Return the chat model configured for 'parser', 'buyer' or 'report'."""
    return ChatOpenAI(model=MODELS[role], temperature=TEMPERATURES[role])


# מקבל ההחלטות של הקונה: הודעות -> BuyerDecision, או None אם הפלט לא תקין
def get_buyer_decider() -> Runnable:
    """Buyer model with structured output; returns None instead of raising on a bad output."""
    structured = get_chat_model("buyer").with_structured_output(
        BuyerDecision, method="function_calling", include_raw=True
    )
    return structured | RunnableLambda(lambda result: result["parsed"])


# המפענח: הודעות -> ParsedRequest, או None אם הפלט לא תקין
def get_parser() -> Runnable:
    """Parser model with structured output; returns None instead of raising on a bad output."""
    structured = get_chat_model("parser").with_structured_output(
        ParsedRequest, method="function_calling", include_raw=True
    )
    return structured | RunnableLambda(lambda result: result["parsed"])


# כותב הדוח: הודעות -> טקסט Markdown
def get_report_writer() -> Runnable:
    """Report model returning plain text."""
    return get_chat_model("report") | StrOutputParser()


# המתרגם: הודעות -> טקסט בעברית (לתצוגה בלבד)
def get_translator() -> Runnable:
    """Translation model returning plain text."""
    return get_chat_model("translate") | StrOutputParser()
