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
    with get_session() as session:
        for src in sources:
            existing = session.execute(
                select(Source).where(Source.username == src["username"])
            ).scalar_one_or_none()
            if existing is None:
                source = Source(
                    username=src["username"],
                    title=src.get("title", src["username"]),
                    topics=json.dumps(src.get("topics", []), ensure_ascii=False),
                    is_active=src.get("active", True),
                )
                session.add(source)
                logger.info(f"Added new source to DB: {src['username']}")
