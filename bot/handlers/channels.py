from pathlib import Path

import yaml
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from loguru import logger

from bot.audit import log_action
from bot.permissions import require_role
from bot.users import get_user_by_tg_id
from config.settings import get_settings

router = Router()


class AddChannel(StatesGroup):
    username = State()
    title = State()
    topics = State()


def _load_sources() -> dict:
    path = Path(get_settings().sources_file)
    if not path.exists():
        return {"channels": []}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"channels": []}


def _save_sources(data: dict) -> None:
    path = Path(get_settings().sources_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


@router.message(Command("channels"))
@require_role("admin")
async def cmd_channels(message: Message) -> None:
    data = _load_sources()
    channels = data.get("channels", [])
    if not channels:
        await message.answer("📭 Каналов нет.\nДобавить — /add_channel")
        return

    lines = ["📡 <b>Telegram-каналы:</b>\n"]
    for i, ch in enumerate(channels, 1):
        status = "✅" if ch.get("active", True) else "⏸"
        topics = ", ".join(ch.get("topics", []))
        lines.append(
            f"{i}. {status} <b>{ch['username']}</b>\n"
            f"   {ch.get('title', '—')}\n"
            f"   Темы: {topics or '—'}\n"
        )

    lines.append(
        "\nКоманды:\n"
        "/add_channel — добавить\n"
        "/toggle_channel @username — вкл/выкл\n"
        "/remove_channel @username — удалить"
    )
    await message.answer("\n".join(lines))


@router.message(Command("add_channel"))
@require_role("admin")
async def cmd_add_channel(message: Message, state: FSMContext) -> None:
    await state.set_state(AddChannel.username)
    await message.answer(
        "➕ <b>Добавление канала</b>\n\n"
        "Шаг 1/3. Username канала с @:\n"
        "<i>Пример: @fintechnews_ru</i>\n\n"
        "/cancel — отменить"
    )


@router.message(AddChannel.username)
async def add_channel_username(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username

    data = _load_sources()
    if any(c["username"].lower() == username.lower() for c in data.get("channels", [])):
        await state.clear()
        await message.answer(f"⚠️ Канал {username} уже добавлен.")
        return

    await state.update_data(username=username)
    await state.set_state(AddChannel.title)
    await message.answer("Шаг 2/3. Название канала (для отображения в Excel):")


@router.message(AddChannel.title)
async def add_channel_title(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddChannel.topics)
    await message.answer(
        "Шаг 3/3. Темы канала через запятую "
        "<i>(подсказка для системы)</i>:\n\n"
        "Пример: <code>финтех, банки, платежи</code>\n\n"
        "Или /skip чтобы пропустить"
    )


@router.message(AddChannel.topics)
async def add_channel_topics(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    topics: list[str] = []
    if message.text.strip() != "/skip":
        topics = [t.strip() for t in message.text.split(",") if t.strip()]

    saved = await state.get_data()
    data = _load_sources()
    data.setdefault("channels", []).append({
        "username": saved["username"],
        "title": saved["title"],
        "topics": topics,
        "active": True,
    })
    _save_sources(data)

    user = get_user_by_tg_id(message.from_user.id)
    log_action(user["id"], "add_channel", "channel", payload={"username": saved["username"]})
    logger.info(f"Channel {saved['username']} added by tg={message.from_user.id}")

    await state.clear()
    await message.answer(
        f"✅ Канал {saved['username']} добавлен.\n\n"
        "Будет включён в следующий автоматический сбор (раз в 30 минут)."
    )


@router.message(Command("toggle_channel"))
@require_role("admin")
async def cmd_toggle_channel(message: Message) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /toggle_channel @username")
        return

    username = parts[1].strip()
    if not username.startswith("@"):
        username = "@" + username

    data = _load_sources()
    for ch in data.get("channels", []):
        if ch["username"].lower() == username.lower():
            ch["active"] = not ch.get("active", True)
            status = "включён ✅" if ch["active"] else "выключен ⏸"
            _save_sources(data)
            user = get_user_by_tg_id(message.from_user.id)
            log_action(user["id"], "toggle_channel", "channel",
                       payload={"username": username, "active": ch["active"]})
            await message.answer(f"Канал {username} — {status}")
            return

    await message.answer(f"❌ Канал {username} не найден.")


@router.message(Command("remove_channel"))
@require_role("admin")
async def cmd_remove_channel(message: Message) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /remove_channel @username")
        return

    username = parts[1].strip()
    if not username.startswith("@"):
        username = "@" + username

    data = _load_sources()
    before = len(data.get("channels", []))
    data["channels"] = [
        c for c in data.get("channels", [])
        if c["username"].lower() != username.lower()
    ]
    if len(data["channels"]) == before:
        await message.answer(f"❌ Канал {username} не найден.")
        return

    _save_sources(data)
    user = get_user_by_tg_id(message.from_user.id)
    log_action(user["id"], "remove_channel", "channel", payload={"username": username})
    logger.info(f"Channel {username} removed by tg={message.from_user.id}")
    await message.answer(
        f"✅ Канал {username} удалён.\n"
        "Уже собранные посты остаются в базе."
    )


@router.message(Command("channel_stats"))
@require_role("admin")
async def cmd_channel_stats(message: Message) -> None:
    parts = message.text.split(maxsplit=1)

    from sqlalchemy import func

    from db.base import get_session
    from db.models import NewsCard, Source, TrendCase

    if len(parts) < 2:
        with get_session() as s:
            rows = (
                s.query(
                    NewsCard.source_title,
                    func.count(NewsCard.id).label("posts"),
                    func.avg(NewsCard.relevance_score).label("avg_score"),
                )
                .group_by(NewsCard.source_title)
                .order_by(func.avg(NewsCard.relevance_score).desc())
                .all()
            )
        lines = ["📊 <b>Сводка по каналам</b>\n"]
        lines.append(f"{'Канал':<28} {'Постов':>7} {'Avg':>5}")
        lines.append("─" * 45)
        for r in rows:
            title = (r.source_title or "—")[:28]
            avg = r.avg_score or 0
            lines.append(f"<code>{title:<28} {r.posts:>7} {avg:>5.1f}</code>")
        lines.append("\nДетали по каналу: /channel_stats @username")
        await message.answer("\n".join(lines))
        return

    username = parts[1].strip()
    if not username.startswith("@"):
        username = "@" + username

    with get_session() as s:
        source = s.query(Source).filter(Source.username == username).first()
        if not source:
            await message.answer(f"❌ Канал {username} не найден в базе.")
            return
        source_title = source.title
        source_active = source.is_active

        posts = s.query(NewsCard).filter(NewsCard.source_title == source_title).count()
        avg_q = s.query(func.avg(NewsCard.relevance_score)).filter(
            NewsCard.source_title == source_title
        ).scalar()
        high = s.query(NewsCard).filter(
            NewsCard.source_title == source_title,
            NewsCard.relevance_label == "high",
        ).count()
        ads = s.query(NewsCard).filter(
            NewsCard.source_title == source_title,
            NewsCard.is_ad == True,  # noqa: E712
        ).count()
        cases = (
            s.query(TrendCase)
            .join(NewsCard, TrendCase.news_card_id == NewsCard.id)
            .filter(NewsCard.source_title == source_title)
            .count()
        )

    await message.answer(
        f"📊 <b>Статистика канала {username}</b>\n\n"
        f"<b>{source_title}</b>\n"
        f"Статус: {'✅ активен' if source_active else '⏸ выключен'}\n\n"
        f"Всего постов: <b>{posts}</b>\n"
        f"Кейсов извлечено: <b>{cases}</b>\n"
        f"Высокая релевантность: <b>{high}</b>\n"
        f"Рекламных постов: <b>{ads}</b>\n"
        f"Средний score: <b>{avg_q or 0:.1f}</b>\n\n"
        f"<i>Управление: /toggle_channel {username} | /remove_channel {username}</i>"
    )
