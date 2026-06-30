import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import feedparser
from loguru import logger
from sqlalchemy import select

from db.base import get_session
from db.models import RawPost


@dataclass
class RssCollectResult:
    source_username: str
    total_fetched: int = 0
    saved: int = 0
    skipped_duplicate: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


def _entry_int_id(entry_id: str) -> int:
    """Derive a stable positive integer from the entry_id for use as RawPost.message_id."""
    return int(hashlib.md5(entry_id.encode()).hexdigest()[:8], 16)


def _entry_hash(source_username: str, entry_id: str) -> int:
    """Derive a stable positive integer from source_username + entry_id."""
    combined = f"{source_username}::{entry_id}"
    return int(hashlib.md5(combined.encode()).hexdigest()[:8], 16)


def _fetch_full_text(url: str) -> str | None:
    """Fetch and extract readable text from a URL using readability-lxml."""
    try:
        import httpx
        from readability import Document

        resp = httpx.get(url, timeout=10, follow_redirects=True)
        doc = Document(resp.text)
        raw = re.sub(r"<[^>]+>", " ", doc.summary())
        text = re.sub(r"\s+", " ", raw).strip()
        return text[:8000] if text else None
    except Exception as e:
        logger.warning(f"Failed to fetch full text from {url}: {e}")
        return None


def _parse_date(entry: object) -> datetime:
    """Parse feedparser entry date to naive UTC datetime; falls back to utcnow."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6])
            except Exception:
                pass
    return datetime.utcnow()


def collect_rss_source(
    source_db_id: int,
    source_username: str,
    feed_url: str,
    fetch_full_text: bool = False,
    days: float = 7,
    source_title: str | None = None,
) -> RssCollectResult:
    """Collect articles from a single RSS feed and save new ones to DB."""
    result = RssCollectResult(source_username=source_username)
    since = datetime.utcnow() - timedelta(days=days)

    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        result.errors += 1
        result.error_messages.append(f"Failed to parse feed {feed_url}: {e}")
        return result

    for entry in feed.entries:
        result.total_fetched += 1

        entry_id = (
            getattr(entry, "id", None)
            or getattr(entry, "link", None)
            or str(result.total_fetched)
        )
        pseudo_message_id = _entry_hash(source_username, entry_id)

        pub_date = _parse_date(entry)
        if pub_date < since:
            result.skipped_empty += 1
            continue

        with get_session() as s:
            exists = s.execute(
                select(RawPost).where(
                    RawPost.source_id == source_db_id,
                    RawPost.message_id == pseudo_message_id,
                )
            ).scalar_one_or_none()
            if exists:
                result.skipped_duplicate += 1
                continue

        link = getattr(entry, "link", None) or ""
        text = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""

        if fetch_full_text and link:
            full = _fetch_full_text(link)
            if full and len(full) > len(text):
                text = full

        if not text.strip():
            result.skipped_empty += 1
            continue

        title = getattr(entry, "title", None) or ""
        if title and not text.startswith(title):
            text = f"{title}\n\n{text}"

        post_hash = hashlib.sha256(text.encode()).hexdigest()[:32]

        try:
            with get_session() as s:
                post = RawPost(
                    source_id=source_db_id,
                    message_id=pseudo_message_id,
                    channel_username=source_username,
                    post_url=link or feed_url,
                    raw_text=text[:8000],
                    published_at=pub_date,
                    has_media=False,
                    is_forwarded=False,
                    text_hash=post_hash,
                )
                s.add(post)
            result.saved += 1
        except Exception as e:
            result.errors += 1
            result.error_messages.append(f"Failed to save entry {entry_id}: {e}")

        time.sleep(0.05)

    logger.info(
        f"RSS {source_username} done — fetched={result.total_fetched}"
        f" saved={result.saved} dupes={result.skipped_duplicate}"
        f" empty={result.skipped_empty} errors={result.errors}"
    )
    return result
