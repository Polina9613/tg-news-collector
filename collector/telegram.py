import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from collector.sources_loader import load_pdf_channels, load_sources, sync_sources_to_db
from config.settings import Settings
from db.base import get_session
from db.models import RawPost, Source


def extract_urls_from_message(message: object) -> list[str]:
    """Извлекает внешние http-ссылки из entities Telethon-сообщения."""
    urls: list[str] = []
    entities = getattr(message, "entities", None)
    text = getattr(message, "text", None)
    if not entities or not text:
        return urls

    for entity in entities:
        if isinstance(entity, MessageEntityTextUrl):
            if entity.url and entity.url.startswith("http"):
                urls.append(entity.url)
        elif isinstance(entity, MessageEntityUrl):
            url = text[entity.offset : entity.offset + entity.length]
            if url.startswith("http"):
                urls.append(url)

    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _is_pdf_post(message: object) -> bool:
    """Return True if the message has a PDF document attachment."""
    doc = getattr(message, "document", None)
    if doc is None:
        return False
    for attr in getattr(doc, "attributes", None) or []:
        file_name = getattr(attr, "file_name", None)
        if file_name and str(file_name).lower().endswith(".pdf"):
            return True
    return False


def _extract_pdf_name(message: object) -> str | None:
    """Return the PDF filename from a message document, or None."""
    doc = getattr(message, "document", None)
    if doc is None:
        return None
    for attr in getattr(doc, "attributes", None) or []:
        file_name = getattr(attr, "file_name", None)
        if file_name and str(file_name).lower().endswith(".pdf"):
            return str(file_name)
    return None


@dataclass
class CollectResult:
    channel_username: str
    total_fetched: int = 0
    saved: int = 0
    skipped_duplicate: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    pdf_posts: list[dict] = field(default_factory=list)


class TelegramCollector:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: TelegramClient | None = None

    async def connect(self) -> None:
        self._client = TelegramClient(
            self._settings.telegram_session_name,
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash,
        )
        await self._client.start(phone=self._settings.telegram_phone)
        logger.info("Connected to Telegram")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            logger.info("Disconnected from Telegram")

    def _get_or_create_source_id(self, username: str) -> int:
        """Возвращает ID источника из БД, создаёт запись если её нет."""
        with get_session() as session:
            src = session.execute(
                select(Source).where(Source.username == f"@{username}")
            ).scalar_one_or_none()
            if src is None:
                src = Source(username=f"@{username}", title=username, topics="[]")
                session.add(src)
                session.flush()  # получаем autoincrement ID до commit
            return src.id

    def _save_post(
        self,
        message: object,
        username: str,
        post_url: str,
        source_id: int,
    ) -> bool:
        """Сохраняет пост в БД. Возвращает True если сохранено, False если дубль."""
        with get_session() as session:
            existing = session.execute(
                select(RawPost).where(
                    RawPost.source_id == source_id,
                    RawPost.message_id == message.id,  # type: ignore[union-attr]
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False
            urls = extract_urls_from_message(message)
            post = RawPost(
                source_id=source_id,
                message_id=message.id,  # type: ignore[union-attr]
                channel_username=username,
                post_url=post_url,
                raw_text=message.text or None,  # type: ignore[union-attr]
                published_at=message.date.replace(tzinfo=None),  # type: ignore[union-attr]
                has_media=message.media is not None,  # type: ignore[union-attr]
                is_forwarded=message.fwd_from is not None,  # type: ignore[union-attr]
                views=message.views,  # type: ignore[union-attr]
                text_hash=None,
                extracted_urls=json.dumps(urls, ensure_ascii=False) if urls else None,
            )
            session.add(post)
        return True

    async def collect_channel(
        self,
        username: str,
        days: int = 7,
        source_id: int | None = None,
        is_pdf_channel: bool = False,
    ) -> CollectResult:
        assert self._client is not None, "Call connect() before collecting"
        clean_username = username.lstrip("@")
        result = CollectResult(channel_username=clean_username)
        # aware UTC — нужен для сравнения с message.date от Telethon (тоже aware)
        offset_date = datetime.now(UTC) - timedelta(days=days)

        if source_id is None:
            source_id = self._get_or_create_source_id(clean_username)

        logger.info(
            f"Collecting @{clean_username} for last {days} days"
            f" (since {offset_date:%Y-%m-%d %H:%M} UTC)"
        )

        try:
            async for message in self._client.iter_messages(
                clean_username,
                limit=500,      # защитный лимит на случай очень активных каналов
                reverse=False,  # от новых к старым — break корректно останавливает цикл
            ):
                # Telethon отдаёт посты от новых к старым; как только дошли до
                # поста старше нужной даты — дальше смотреть незачем
                if message.date < offset_date:
                    break

                result.total_fetched += 1

                if result.total_fetched % 50 == 0:
                    logger.info(f"@{clean_username}: fetched {result.total_fetched} posts...")

                try:
                    if is_pdf_channel and _is_pdf_post(message):
                        filename = _extract_pdf_name(message) or "unknown.pdf"
                        post_url = f"https://t.me/{clean_username}/{message.id}"
                        result.pdf_posts.append({
                            "filename": filename,
                            "post_url": post_url,
                            "post_text": (message.text or "")[:500],
                            "channel_username": f"@{clean_username}",
                            "channel_title": clean_username,
                        })
                        result.skipped_empty += 1
                        continue

                    if not message.text and message.media is None:
                        result.skipped_empty += 1
                        continue

                    post_url = f"https://t.me/{clean_username}/{message.id}"
                    saved = self._save_post(
                        message=message,
                        username=clean_username,
                        post_url=post_url,
                        source_id=source_id,
                    )
                    if saved:
                        result.saved += 1
                    else:
                        result.skipped_duplicate += 1

                    await asyncio.sleep(0.5)

                except FloodWaitError as e:
                    wait_sec = e.seconds + 5
                    logger.warning(f"FloodWait on @{clean_username}: sleeping {wait_sec}s")
                    await asyncio.sleep(wait_sec)
                except Exception as e:
                    msg = f"Error processing message {message.id}: {e}"
                    logger.error(msg)
                    result.errors += 1
                    result.error_messages.append(msg)

        except Exception as e:
            msg = f"Failed to collect @{clean_username}: {e}"
            logger.error(msg)
            result.errors += 1
            result.error_messages.append(msg)

        logger.info(
            f"@{clean_username} done — fetched={result.total_fetched}"
            f" saved={result.saved} dupes={result.skipped_duplicate}"
            f" empty={result.skipped_empty} errors={result.errors}"
        )
        return result

    async def collect_all(self, days: int = 7) -> list[CollectResult]:
        assert self._client is not None, "Call connect() before collecting"
        sources = load_sources(self._settings.sources_file)
        if not sources:
            logger.warning("No active sources found in sources file")
            return []

        sync_sources_to_db(sources)

        pdf_sources = load_pdf_channels(self._settings.sources_file)
        if pdf_sources:
            sync_sources_to_db(pdf_sources)

        pdf_channel_set = {ch["username"].lstrip("@").lower() for ch in pdf_sources}

        with get_session() as session:
            db_sources = session.execute(select(Source)).scalars().all()
            source_map = {s.username: s.id for s in db_sources}

        results = []
        for src in sources:
            username = src["username"]
            source_id = source_map.get(username)
            result = await self.collect_channel(
                username=username,
                days=days,
                source_id=source_id,
            )
            results.append(result)

        for src in pdf_sources:
            username = src["username"]
            source_id = source_map.get(username)
            if source_id is None:
                source_id = self._get_or_create_source_id(username.lstrip("@"))
            result = await self.collect_channel(
                username=username,
                days=days,
                source_id=source_id,
                is_pdf_channel=True,
            )
            results.append(result)

        return results
