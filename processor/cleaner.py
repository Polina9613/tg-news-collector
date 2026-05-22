import hashlib
import re

_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_MD_BOLD_ITALIC_RE = re.compile(r'\*{1,3}([^*]+)\*{1,3}')
_MD_UNDERLINE_RE = re.compile(r'_{1,2}([^_]+)_{1,2}')
_MD_STRIKE_RE = re.compile(r'~~([^~]+)~~')
_MD_SPOILER_RE = re.compile(r'\|\|([^|]+)\|\|')
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U00002600-\U000026FF"
    "\U000025A0-\U000025FF"
    "‍️⃣"
    "]+",
    flags=re.UNICODE,
)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = _MD_LINK_RE.sub(r'\1', text)
    text = _MD_BOLD_ITALIC_RE.sub(r'\1', text)
    text = _MD_UNDERLINE_RE.sub(r'\1', text)
    text = _MD_STRIKE_RE.sub(r'\1', text)
    text = _MD_SPOILER_RE.sub(r'\1', text)
    text = _HTML_TAG_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_HASHTAG_ONLY_RE = re.compile(r'^(#\w+\s*)+$')


def extract_title(text: str) -> str:
    if not text:
        return "Без заголовка"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _HASHTAG_ONLY_RE.match(line):
            continue
        if len(line) < 10:
            continue
        return line[:150]
    return "Без заголовка"
