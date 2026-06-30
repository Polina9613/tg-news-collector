import json

import yaml
from loguru import logger
from sqlalchemy import select

from db.base import get_session
from db.models import Source


def load_sources(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Sources file not found: {path}")
        return []

    channels = data.get("channels", [])
    result = []
    for ch in channels:
        if "username" not in ch:
            logger.warning(f"Channel missing 'username' field, skipping: {ch}")
            continue
        if not ch.get("active", True):
            continue
        result.append(ch)
    return result


def sync_sources_to_db(sources: list[dict]) -> None:
    """Синхронизирует список каналов из YAML в таблицу sources.
    Добавляет новые источники, обновляет topics и is_active у существующих.
    """
    with get_session() as session:
        for src in sources:
            topics_json = json.dumps(src.get("topics", []), ensure_ascii=False)
            existing = session.execute(
                select(Source).where(Source.username == src["username"])
            ).scalar_one_or_none()
            if existing is None:
                source = Source(
                    username=src["username"],
                    title=src.get("title", src["username"]),
                    topics=topics_json,
                    is_active=src.get("active", True),
                )
                session.add(source)
                logger.info(f"Added new source to DB: {src['username']}")
            else:
                existing.topics = topics_json
                existing.is_active = src.get("active", True)
                if src.get("title"):
                    existing.title = src["title"]


def load_rss_sources(path: str) -> list[dict]:
    """Load rss_sources section from YAML. Returns active RSS feeds."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Sources file not found: {path}")
        return []

    result = []
    for ch in data.get("rss_sources", []):
        if "username" not in ch or "feed_url" not in ch:
            logger.warning(f"RSS source missing required fields, skipping: {ch}")
            continue
        if not ch.get("active", True):
            continue
        result.append(ch)
    return result


def sync_rss_sources_to_db(yaml_path: str) -> list[dict]:
    """Sync RSS sources to DB and return list of dicts with db_id added."""
    sources = load_rss_sources(yaml_path)
    result = []

    with get_session() as session:
        for src in sources:
            topics_json = json.dumps(src.get("topics", []), ensure_ascii=False)
            existing = session.execute(
                select(Source).where(Source.username == src["username"])
            ).scalar_one_or_none()

            if existing is None:
                new_src = Source(
                    username=src["username"],
                    title=src.get("title", src["username"]),
                    topics=topics_json,
                    is_active=True,
                )
                session.add(new_src)
                session.flush()
                db_id = new_src.id
                logger.info(f"Added new RSS source to DB: {src['username']}")
            else:
                existing.topics = topics_json
                existing.is_active = True
                if src.get("title"):
                    existing.title = src["title"]
                db_id = existing.id

            result.append({**src, "db_id": db_id})

    return result


def load_pdf_channels(path: str) -> list[dict]:
    """Load pdf_channels section from YAML. Returns active PDF channels."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Sources file not found: {path}")
        return []

    result = []
    for ch in data.get("pdf_channels", []):
        if "username" not in ch:
            continue
        if not ch.get("active", True):
            continue
        result.append(ch)
    return result
