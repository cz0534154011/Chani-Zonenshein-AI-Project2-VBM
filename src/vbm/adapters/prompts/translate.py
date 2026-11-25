"""Translation prompt: numbered English lines -> the same numbered lines in Hebrew (display only)."""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM = ("Translate each numbered line to Hebrew. Keep every number exactly. "
          "Return the same numbering, one line per item, nothing else.")


# בניית הפרומפט של התרגום משורות ממוספרות
def build_translate_prompt(texts: list[str]) -> list[BaseMessage]:
    """Return the system and user messages for translating the given lines."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    return [SystemMessage(content=SYSTEM), HumanMessage(content=numbered)]
