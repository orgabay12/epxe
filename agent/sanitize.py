import re
import unicodedata
import html

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
    # Decode HTML entities (e.g., &quot;) and remove literal Unicode escape sequences like \u0022
    normalized = html.unescape(normalized)
    normalized = re.sub(r"\\u[0-9a-fA-F]{4}", "", normalized)
    cleaned = _allowed_pattern.sub("", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip() 