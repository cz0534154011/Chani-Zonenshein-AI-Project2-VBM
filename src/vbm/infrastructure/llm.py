"""VBM language models: one OpenAI chat model per role, created only when first needed (infrastructure layer)."""

from functools import lru_cache

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from vbm.application.dto import BuyerDecision, ParsedRequest
from vbm.infrastructure.settings import MODELS, TEMPERATURES


# מודל השפה של תפקיד מסוים, לפי settings; נוצר פעם אחת בלבד
@lru_cache(maxsize=None)
def get_chat_model(role: str) -> ChatOpenAI:
    """Return the chat model configured for 'parser', 'buyer', 'report' or 'translate'."""
    return ChatOpenAI(model=MODELS[role], temperature=TEMPERATURES[role])


# מודל הקונה: הודעות -> BuyerDecision, או None אם הפלט לא תקין
def buyer_model() -> Runnable:
    """Buyer model with structured output; returns None instead of raising on a bad output."""
    structured = get_chat_model("buyer").with_structured_output(
        BuyerDecision, method="function_calling", include_raw=True
    )
    return structured | RunnableLambda(lambda result: result["parsed"])


# מודל המפענח: הודעות -> ParsedRequest, או None אם הפלט לא תקין
def parser_model() -> Runnable:
    """Parser model with structured output; returns None instead of raising on a bad output."""
    structured = get_chat_model("parser").with_structured_output(
        ParsedRequest, method="function_calling", include_raw=True
    )
    return structured | RunnableLambda(lambda result: result["parsed"])


# מודל הדוח: הודעות -> טקסט Markdown
def report_model() -> Runnable:
    """Report model returning plain text."""
    return get_chat_model("report") | StrOutputParser()


# מודל התרגום: הודעות -> טקסט בעברית (לתצוגה בלבד)
def translate_model() -> Runnable:
    """Translation model returning plain text."""
    return get_chat_model("translate") | StrOutputParser()
