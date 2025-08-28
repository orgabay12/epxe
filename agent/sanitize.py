import re
import unicodedata

_allowed_pattern = re.compile(r"[^A-Za-z0-9\u0590-\u05FF \-\'&\./(),]")

def sanitize_merchant(value: str) -> str:
    if not isinstance(value, str):
        return value
    normalized = unicodedata.normalize("NFKC", value)
    normalized = (
        normalized
        .replace("\u00A0", " ")  # NBSP
        .replace("\u202F", " ")  # Narrow NBSP
        .replace("\u2007", " ")  # Figure space
    )
    cleaned = _allowed_pattern.sub("", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip() 