"""VBM model gateways: implement the application ports with a prompt plus any model that has invoke(messages)."""

from collections.abc import Callable
from typing import Any, Protocol

from vbm.adapters.prompts import PROMPT_VERSIONS, buyer_v1, buyer_v2
from vbm.adapters.prompts.parser import build_parser_prompt
from vbm.adapters.prompts.report import build_report_prompt
from vbm.adapters.prompts.translate import build_translate_prompt
from vbm.application.dto import BuyerDecision, ParsedRequest
from vbm.domain.schemas import BuyerTerms, TranscriptEntry


# כל מודל (אמיתי או מזויף בבדיקות) שמקבל הודעות ומחזיר תשובה
class Model(Protocol):
    def invoke(self, messages: list) -> Any:
        ...


# יוצר המודל: נקרא בכל שימוש, כך שהמודל האמיתי נוצר רק כשבאמת צריך אותו
ModelFactory = Callable[[], Model]


# המפענח: בקשה חופשית -> ParsedRequest, או None
class LLMRequestParser:
    """RequestParser port over a structured-output model."""

    def __init__(self, model: ModelFactory):
        self._model = model

    def parse(self, raw_request: str) -> ParsedRequest | None:
        return self._model().invoke(build_parser_prompt(raw_request))


# הקונה: בוחר את הפרומפט לפי הגרסה ומבקש החלטה מהמודל
class LLMBuyerDecider:
    """BuyerDecider port: prompt v1 or v2, built only from buyer data, transcript and guardrail feedback."""

    def __init__(self, model: ModelFactory):
        self._model = model

    def decide(self, buyer: BuyerTerms, transcript: list[TranscriptEntry], guardrail_feedback: str | None,
               round_no: int, max_rounds: int, prompt_version: str) -> BuyerDecision | None:
        model = self._model()
        if prompt_version not in PROMPT_VERSIONS:
            raise ValueError(f"unknown prompt_version: {prompt_version}")
        if prompt_version == "v1":
            messages = buyer_v1.build_buyer_prompt(buyer, transcript, guardrail_feedback)
        else:
            messages = buyer_v2.build_buyer_prompt(buyer, transcript, guardrail_feedback, round_no, max_rounds)
        return model.invoke(messages)


# כותב הדוח: ReportData -> Markdown
class LLMReportWriter:
    """ReportWriter port over a text model."""

    def __init__(self, model: ModelFactory):
        self._model = model

    def write(self, report_data: dict, unverified: list[str]) -> str:
        return self._model().invoke(build_report_prompt(report_data, unverified))


# המתרגם: שורות ממוספרות באנגלית -> עברית; שורה שלא תורגמה נשארת כמו שהיא
class LLMTranslator:
    """Translator port over a text model."""

    def __init__(self, model: ModelFactory):
        self._model = model

    def translate(self, texts: list[str]) -> list[str]:
        answer = self._model().invoke(build_translate_prompt(texts))
        out = {}
        for line in answer.splitlines():
            head, _, rest = line.partition(".")
            if head.strip().isdigit():
                out[int(head)] = rest.strip()
        return [out.get(i, t) for i, t in enumerate(texts, 1)]
