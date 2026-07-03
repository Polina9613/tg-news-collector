from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy import func

from bot.permissions import require_role

router = Router()

RESULTS_PER_PAGE = 5
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
# Telegram callback_data ограничен 64 байтами; резервируем место под префикс и номер страницы
_CB_QUERY_LIMIT = 40


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short(text: str | None, n: int = 200) -> str:
    if not text:
        return "—"
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _cb_query(query: str) -> str:
    """Усекает строку до _CB_QUERY_LIMIT байт для использования в callback_data."""
    encoded = query.encode("utf-8")
    if len(encoded) <= _CB_QUERY_LIMIT:
        return query
    return encoded[:_CB_QUERY_LIMIT].decode("utf-8", errors="ignore")


def _format_case_short(case: dict, idx: int) -> str:
    url_line = (
        f"\n<a href='{case['source_url']}'>Источник</a>"
        if case.get("source_url") else ""
    )
    return (
        f"<b>{idx}. {case['case_title'] or 'Без названия'}</b>\n"
        f"Тренд: {case['trend_name'] or '—'}\n"
        f"{case['company'] or '—'} | {case['market'] or '—'}\n"
        f"{_short(case['description'], 180)}"
        f"{url_line}"
    )


def _pagination_keyboard(
    prefix: str, query: str, page: int, total_pages: int
) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    q = _cb_query(query)
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(
            text="⬅️ Назад", callback_data=f"{prefix}:{q}:{page - 1}"
        ))
    row.append(InlineKeyboardButton(
        text=f"{page + 1}/{total_pages}", callback_data="noop"
    ))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(
            text="Далее ➡️", callback_data=f"{prefix}:{q}:{page + 1}"
        ))
    return InlineKeyboardMarkup(inline_keyboard=[row])


# ── Универсальный поиск ───────────────────────────────────────────────────────

def _search_cases(
    query: str | None = None,
    company: str | None = None,
    topic: str | None = None,
    trend_id: int | None = None,
    days: int | None = None,
    offset: int = 0,
    limit: int = RESULTS_PER_PAGE,
) -> tuple[list[dict], int]:
    """Поиск кейсов с Python-стороной фильтрацией текста.

    SQLite не поддерживает регистронезависимый LIKE для кириллицы,
    поэтому текстовые фильтры применяются после выборки в Python.
    """
    from db.base import get_session
    from db.models import NewsCard, TrendCase

    with get_session() as s:
        q = s.query(TrendCase).outerjoin(NewsCard, TrendCase.news_card_id == NewsCard.id)

        # Точные / диапазонные фильтры — SQL справляется корректно
        if trend_id is not None:
            q = q.filter(TrendCase.trend_id == trend_id)
        if days is not None:
            since = datetime.utcnow() - timedelta(days=days)
            q = q.filter(
                (NewsCard.published_at >= since) | (TrendCase.created_at >= since)
            )

        q = q.order_by(TrendCase.created_at.desc())
        all_cases = q.all()

        # Python-сторона: регистронезависимая фильтрация работает для любого языка
        def _matches(tc: TrendCase) -> bool:
            nc = tc.news_card

            if query:
                ql = query.lower().strip()
                haystack = " ".join(filter(None, [
                    tc.case_title or "",
                    tc.description or "",
                    tc.value or "",
                    tc.how_it_works or "",
                    tc.company or "",
                    tc.trend_name or "",
                ])).lower()
                if ql not in haystack:
                    return False

            if company:
                cl = company.lower()
                if not tc.company or cl not in tc.company.lower():
                    return False

            if topic:
                tl = topic.lower()
                topics_str = (nc.topics or "").lower() if nc else ""
                tags_str = (nc.tags or "").lower() if nc else ""
                trend_lc = (tc.trend_name or "").lower()
                if tl not in topics_str and tl not in tags_str and tl not in trend_lc:
                    return False

            return True

        filtered = [tc for tc in all_cases if _matches(tc)]
        total = len(filtered)
        page_cases = filtered[offset: offset + limit]

        return [
            {
                "id":          tc.id,
                "trend_name":  tc.trend_name,
                "case_title":  tc.case_title,
                "company":     tc.company,
                "description": tc.description,
                "value":       tc.value,
                "market":      tc.market,
                "source_url":  tc.source_url,
            }
            for tc in page_cases
        ], total


async def _send_search_results(
    target: Message | CallbackQuery,
    prefix: str,
    query_str: str,
    page: int,
    **search_kwargs,
) -> None:
    offset = page * RESULTS_PER_PAGE
    cases, total = _search_cases(offset=offset, **search_kwargs)

    msg = target if isinstance(target, Message) else target.message

    if total == 0:
        text = f"По запросу «{query_str}» ничего не найдено."
        if isinstance(target, Message):
            await msg.answer(text)
        else:
            await msg.edit_text(text)
            await target.answer()
        return

    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    start_idx = offset + 1

    lines = [
        f"<b>Результаты по запросу «{query_str}»</b>",
        f"Найдено: {total} | Страница {page + 1}/{total_pages}\n",
    ]
    for i, case in enumerate(cases):
        lines.append(_format_case_short(case, start_idx + i))
        lines.append("")

    text = "\n".join(lines)
    kb = _pagination_keyboard(prefix, query_str, page, total_pages)

    if isinstance(target, Message):
        await msg.answer(text, reply_markup=kb, link_preview_options=_NO_PREVIEW)
    else:
        await msg.edit_text(text, reply_markup=kb, link_preview_options=_NO_PREVIEW)
        await target.answer()


# ── /search ───────────────────────────────────────────────────────────────────

@router.message(Command("search"))
@require_role("admin", "analyst")
async def cmd_search(message: Message) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "<b>Поиск по тексту кейсов</b>\n\n"
            "Использование: <code>/search запрос</code>\n"
            "Примеры:\n"
            "/search биометрия\n"
            "/search цифровой рубль\n"
            "/search face pay"
        )
        return
    query = parts[1].strip()
    await _send_search_results(message, "srch", query, 0, query=query)


@router.callback_query(F.data.startswith("srch:"))
async def handle_search_page(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    query = parts[1]
    page = int(parts[2])
    await _send_search_results(call, "srch", query, page, query=query)


# ── /company ──────────────────────────────────────────────────────────────────

@router.message(Command("company"))
@require_role("admin", "analyst")
async def cmd_company(message: Message) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "<b>Поиск по компании</b>\n\n"
            "Использование: <code>/company название</code>\n"
            "Примеры:\n"
            "/company Сбер\n"
            "/company ВТБ\n"
            "/company Яндекс"
        )
        return
    company = parts[1].strip()
    await _send_search_results(message, "comp", company, 0, company=company)


@router.callback_query(F.data.startswith("comp:"))
async def handle_company_page(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    company = parts[1]
    page = int(parts[2])
    await _send_search_results(call, "comp", company, page, company=company)


# ── /topic ────────────────────────────────────────────────────────────────────

@router.message(Command("topic"))
@require_role("admin", "analyst")
async def cmd_topic(message: Message) -> None:
    """
    /topic <тема>        — кейсы по теме за всё время
    /topic <тема> <дней> — кейсы по теме за последние N дней
    """
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "🏷 <b>Поиск по теме или тегу</b>\n\n"
            "Ищет кейсы где тема упоминается в темах поста, в тегах "
            "или в названии тренда.\n\n"
            "Использование:\n"
            "<code>/topic ИИ</code> — за всё время\n"
            "<code>/topic ИИ 30</code> — за последние 30 дней\n"
            "<code>/topic Биометрия 90</code> — за 3 месяца\n\n"
            "<b>Доступные темы:</b>\n"
            "Финтех, Банки, Платежи, Биометрия, ИИ, ИТ-инфраструктура, "
            "Импортозамещение, Кибербезопасность, HR, Обучение, Регуляторика, "
            "МСБ, Розница, Клиентский сервис, Крипто / Блокчейн, "
            "Геймификация, Маркетинг, КСО / Самообслуживание"
        )
        return

    days: int | None = None
    if len(parts) == 3:
        try:
            days = int(parts[2])
            if days < 1 or days > 365:
                raise ValueError
            topic = parts[1].strip()
        except ValueError:
            topic = f"{parts[1]} {parts[2]}".strip()
    else:
        topic = parts[1].strip()

    period_label = f" за {days} дней" if days else " за всё время"
    query_str = f"{topic}{period_label}"

    await _send_search_results(message, "tpc", query_str, page=0, topic=topic, days=days)


@router.callback_query(F.data.startswith("tpc:"))
async def handle_topic_page(call: CallbackQuery) -> None:
    import re as _re
    parts = call.data.split(":", 2)
    query_str = parts[1]
    page = int(parts[2])

    match_days = _re.search(r" за (\d+) дней$", query_str)
    if match_days:
        days: int | None = int(match_days.group(1))
        topic = query_str[: match_days.start()].strip()
    else:
        days = None
        topic = query_str.replace(" за всё время", "").strip()

    await _send_search_results(call, "tpc", query_str, page=page, topic=topic, days=days)


# ── /trends ───────────────────────────────────────────────────────────────────

@router.message(Command("trends"))
@require_role("admin", "analyst")
async def cmd_trends(message: Message) -> None:
    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        rows = (
            s.query(
                Trend.id,
                Trend.name,
                Trend.first_seen_at,
                func.count(TrendCase.id).label("cnt"),
            )
            .outerjoin(TrendCase, TrendCase.trend_id == Trend.id)
            .group_by(Trend.id)
            .order_by(func.count(TrendCase.id).desc())
            .all()
        )
        data = [
            (
                r.id,
                r.name,
                r.cnt,
                r.first_seen_at.strftime("%m.%Y") if r.first_seen_at else "—",
            )
            for r in rows
        ]

    if not data:
        await message.answer("Трендов пока нет.")
        return

    lines = ["<b>Тренды в базе знаний</b>\n"]
    for tid, name, cnt, first in data:
        lines.append(f"• <b>#{tid}</b> {name} — {cnt} кейсов <i>(c {first})</i>")
    lines.append("\nДетали: <code>/trend &lt;id&gt;</code>")

    await message.answer("\n".join(lines))


# ── /trend <id> ───────────────────────────────────────────────────────────────

@router.message(Command("trend"))
@require_role("admin", "analyst")
async def cmd_trend_info(message: Message) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: <code>/trend &lt;id&gt;</code>\nПример: /trend 3")
        return
    try:
        trend_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        trend = s.get(Trend, trend_id)
        if not trend:
            await message.answer(f"Тренд #{trend_id} не найден.")
            return
        cases = s.query(TrendCase).filter(TrendCase.trend_id == trend_id).all()
        data = {
            "name":          trend.name,
            "description":   trend.description,
            "first_seen_at": trend.first_seen_at,
            "cases_count":   len(cases),
            "companies":     sorted({c.company for c in cases if c.company}),
            "markets":       [c.market for c in cases if c.market],
            "periods":       [c.period_label for c in cases if c.period_label],
        }

    period_counts = Counter(data["periods"]).most_common(6)
    market_counts = Counter(data["markets"]).most_common(3)

    period_lines = "\n".join(f"  • {p}: {c} кейсов" for p, c in period_counts) or "  —"
    market_lines = ", ".join(f"{m} ({c})" for m, c in market_counts) or "—"
    companies_str = ", ".join(data["companies"][:15]) or "—"
    first = data["first_seen_at"].strftime("%d.%m.%Y") if data["first_seen_at"] else "—"

    await message.answer(
        f"<b>Тренд #{trend_id}: {data['name']}</b>\n\n"
        f"<i>{data['description'] or 'Без описания'}</i>\n\n"
        f"Первый кейс: {first}\n"
        f"Всего кейсов: {data['cases_count']}\n\n"
        f"<b>По периодам:</b>\n{period_lines}\n\n"
        f"<b>Компании:</b> {companies_str}\n"
        f"<b>Рынки:</b> {market_lines}\n\n"
        f"Все кейсы: <code>/search_trend {trend_id}</code>"
    )


# ── /search_trend <id> ────────────────────────────────────────────────────────

@router.message(Command("search_trend"))
@require_role("admin", "analyst")
async def cmd_search_trend(message: Message) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: <code>/search_trend &lt;id&gt;</code>")
        return
    try:
        trend_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    await _send_search_results(message, "strend", str(trend_id), 0, trend_id=trend_id)


@router.callback_query(F.data.startswith("strend:"))
async def handle_trend_page(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    trend_id = int(parts[1])
    page = int(parts[2])
    await _send_search_results(call, "strend", str(trend_id), page, trend_id=trend_id)


# ── /digest_now ───────────────────────────────────────────────────────────────

@router.message(Command("digest_now"))
async def cmd_digest_now(message: Message) -> None:
    """Последний дайджест — доступно всем."""
    digests_dir = Path("data/digests")
    if not digests_dir.exists():
        await message.answer("Дайджестов пока нет.")
        return

    digests = sorted(digests_dir.glob("digest_*.docx"), reverse=True)
    if not digests:
        await message.answer("Дайджестов пока нет.")
        return

    latest = digests[0]
    date_part = latest.stem.replace("digest_", "")
    await message.answer_document(
        FSInputFile(latest),
        caption=f"Последний финтех-дайджест ({date_part})"
    )


# ── /research ─────────────────────────────────────────────────────────────────

@router.message(Command("research"))
async def cmd_research(message: Message) -> None:
    """
    /research "будущее офлайн платежей"
    /research "ИИ в скоринге" 90   — с ограничением по дням
    """
    import asyncio
    import re as _re

    text = message.text.replace("/research", "", 1).strip()
    if not text:
        await message.answer(
            "Использование:\n"
            '/research "тема исследования"\n'
            '/research "тема исследования" 90  — за последние 90 дней\n\n'
            '/research "биометрические платежи"'
        )
        return

    match = _re.match(r'"([^"]+)"\s*(\d+)?', text)
    if match:
        query = match.group(1)
        days = int(match.group(2)) if match.group(2) else None
    else:
        query = text
        days = None

    status_msg = await message.answer(f"Готовлю исследование по теме «{query}»…")

    def _run():
        from config.settings import get_settings
        from llm.factory import create_llm_provider
        from research.generator import generate_research

        settings = get_settings()
        provider = create_llm_provider(settings)
        return generate_research(provider, query, days=days)

    result = await asyncio.to_thread(_run)

    if not result:
        await status_msg.edit_text(
            f"Не найдено достаточно кейсов по теме «{query}».\n"
            f"Попробуйте более широкую формулировку или посмотрите /trends."
        )
        return

    await status_msg.edit_text(
        f"Готово: «{result.query}»\n"
        f"Кейсов: {result.cases_used} | Тренды: {', '.join(result.trends_covered)}"
    )

    await message.answer_document(FSInputFile(result.output_path))


# ── /noop — заглушка для кнопки счётчика страниц ─────────────────────────────

@router.callback_query(F.data == "noop")
async def handle_noop(call: CallbackQuery) -> None:
    await call.answer()
