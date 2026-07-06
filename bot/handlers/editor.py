import asyncio
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from loguru import logger

from bot.audit import log_action
from bot.permissions import require_role
from bot.users import get_user_by_tg_id

router = Router()

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# ── /review_week constants ─────────────────────────────────────────────────────

REVIEW_FILTERS = {
    "all":          ("Все кейсы",        None),
    "auto":         ("Авто-обработка",   "auto"),
    "needs_review": ("Требуют проверки", "needs_review"),
    "approved":     ("Одобренные",       "approved"),
    "rejected":     ("Отклонённые",      "rejected"),
    "duplicates":   ("Дубликаты",        "duplicates"),
}

REVIEW_SORTS = {
    "score": "По релевантности",
    "date":  "По дате",
}

REVIEW_PERIODS = {
    7:  "За 7 дней",
    30: "За 30 дней",
    0:  "За всё время",
}


# ── FSM States ────────────────────────────────────────────────────────────────

class EditCase(StatesGroup):
    choosing_field = State()
    entering_value = State()


class AddCase(StatesGroup):
    trend_name   = State()
    case_title   = State()
    company      = State()
    description  = State()
    how_it_works = State()
    value        = State()
    market       = State()
    source_url   = State()


# ── Constants ─────────────────────────────────────────────────────────────────

EDITABLE_FIELDS = {
    "1": ("trend_name",   "Тренд"),
    "2": ("case_title",   "Название кейса"),
    "3": ("company",      "Компания"),
    "4": ("description",  "Описание"),
    "5": ("how_it_works", "Как работает"),
    "6": ("value",        "Ценность"),
    "7": ("market",       "Рынок"),
    "8": ("source_url",   "Ссылка"),
}

MARKET_OPTIONS = ["Россия", "Мир", "Россия и мир"]


# ── DB helpers (sync, called from handlers directly — SQLite is fast) ─────────

def _get_case(case_id: int) -> dict | None:
    from db.base import get_session
    from db.models import NewsCard, TrendCase
    with get_session() as s:
        row = (
            s.query(TrendCase, NewsCard)
            .join(NewsCard, TrendCase.news_card_id == NewsCard.id)
            .filter(TrendCase.id == case_id)
            .first()
        )
        if not row:
            return None
        tc, nc = row
        return {
            "id":              tc.id,
            "trend_name":      tc.trend_name,
            "case_title":      tc.case_title,
            "company":         tc.company,
            "description":     tc.description,
            "how_it_works":    tc.how_it_works,
            "value":           tc.value,
            "market":          tc.market,
            "source_url":      tc.source_url,
            "source_title":    nc.source_title,
            "review_status":   nc.review_status,
            "news_card_id":    nc.id,
            "relevance_score": nc.relevance_score,
        }



# ── FSM: выбор поля ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ef:"), EditCase.choosing_field)
async def handle_field_choice(call: CallbackQuery, state: FSMContext) -> None:
    parts   = call.data.split(":")
    choice  = parts[1]
    case_id = int(parts[2])

    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Редактирование отменено.")
        await call.answer()
        return

    if choice not in EDITABLE_FIELDS:
        await call.answer("Неизвестное поле")
        return

    field_attr, field_label = EDITABLE_FIELDS[choice]
    await state.update_data(field_attr=field_attr, field_label=field_label, case_id=case_id)

    if field_attr == "market":
        await state.set_state(EditCase.entering_value)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=m, callback_data=f"mkt:{m}:{case_id}")]
            for m in MARKET_OPTIONS
        ])
        await call.message.answer("Выберите рынок:", reply_markup=kb)
    else:
        case = _get_case(case_id)
        current = case.get(field_attr) or "—" if case else "—"
        await state.set_state(EditCase.entering_value)
        await call.message.answer(
            f"<b>{field_label}</b>\n\n"
            f"Сейчас: <i>{current}</i>\n\n"
            "Введите новое значение (или /cancel чтобы отменить):"
        )

    await call.answer()


# ── FSM: ввод значения ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mkt:"), EditCase.entering_value)
async def handle_market_choice(call: CallbackQuery, state: FSMContext) -> None:
    parts        = call.data.split(":")
    market_value = parts[1]
    case_id      = int(parts[2])
    await _save_field(call.message, state, market_value, case_id, "market", call=call)


@router.message(EditCase.entering_value)
async def handle_field_value(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Редактирование отменено.")
        return
    data = await state.get_data()
    await _save_field(
        message, state,
        message.text.strip(),
        data["case_id"],
        data["field_attr"],
    )


async def _save_field(
    message: Message,
    state: FSMContext,
    new_value: str,
    case_id: int,
    field_attr: str,
    call: CallbackQuery | None = None,
) -> None:
    from db.base import get_session
    from db.models import TrendCase

    with get_session() as s:
        tc = s.get(TrendCase, case_id)
        if not tc:
            await message.answer("Кейс не найден.")
            await state.clear()
            return
        old_value = getattr(tc, field_attr)
        setattr(tc, field_attr, new_value)

    user_tg_id = call.from_user.id if call else message.from_user.id
    user = get_user_by_tg_id(user_tg_id)
    if user:
        log_action(
            user["id"], "edit_case", "case", case_id,
            {"field": field_attr, "old": old_value, "new": new_value},
        )

    await state.clear()
    await message.answer(
        f"Поле <b>{field_attr}</b> обновлено в кейсе #{case_id}.\n\n"
        f"Было: <i>{old_value or '—'}</i>\n"
        f"Стало: <i>{new_value}</i>"
    )
    if call:
        await call.answer()


# ── /add — добавить кейс вручную ─────────────────────────────────────────────

@router.message(Command("add"))
@require_role("admin")
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddCase.trend_name)
    await message.answer(
        "<b>Добавление нового кейса</b>\n\n"
        "Шаг 1/8. Введите название тренда:\n"
        "<i>Например: Биометрические платежи</i>\n\n"
        "/cancel — отменить"
    )


@router.message(AddCase.trend_name)
async def add_trend_name(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    await state.update_data(trend_name=message.text.strip())
    await state.set_state(AddCase.case_title)
    await message.answer("Шаг 2/8. Название кейса:")


@router.message(AddCase.case_title)
async def add_case_title(message: Message, state: FSMContext) -> None:
    await state.update_data(case_title=message.text.strip())
    await state.set_state(AddCase.company)
    await message.answer("Шаг 3/8. Компания:")


@router.message(AddCase.company)
async def add_company(message: Message, state: FSMContext) -> None:
    await state.update_data(company=message.text.strip())
    await state.set_state(AddCase.description)
    await message.answer("Шаг 4/8. Описание (2-4 предложения):")


@router.message(AddCase.description)
async def add_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await state.set_state(AddCase.how_it_works)
    await message.answer("Шаг 5/8. Как работает (или /skip):")


@router.message(AddCase.how_it_works)
async def add_how_it_works(message: Message, state: FSMContext) -> None:
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(how_it_works=val)
    await state.set_state(AddCase.value)
    await message.answer("Шаг 6/8. Ценность (почему важно для отрасли):")


@router.message(AddCase.value)
async def add_value(message: Message, state: FSMContext) -> None:
    await state.update_data(value=message.text.strip())
    await state.set_state(AddCase.market)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=m, callback_data=f"addmkt:{m}")]
        for m in MARKET_OPTIONS
    ])
    await message.answer("Шаг 7/8. Рынок:", reply_markup=kb)


@router.callback_query(F.data.startswith("addmkt:"), AddCase.market)
async def add_market(call: CallbackQuery, state: FSMContext) -> None:
    market = call.data.split(":")[1]
    await state.update_data(market=market)
    await state.set_state(AddCase.source_url)
    await call.message.answer("Шаг 8/8. Ссылка на источник (или /skip):")
    await call.answer()


@router.message(AddCase.source_url)
async def add_source_url(message: Message, state: FSMContext) -> None:
    val = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    data["source_url"] = val

    def _save() -> int:
        from db.base import get_session
        from db.models import Trend, TrendCase

        def _find_trend_id(name: str) -> int | None:
            name_lower = name.lower()
            with get_session() as s:
                for t in s.query(Trend).filter(Trend.status == "active").all():
                    if name_lower in t.name.lower() or t.name.lower() in name_lower:
                        return t.id
            return None

        trend_id = _find_trend_id(data["trend_name"])
        with get_session() as s:
            tc = TrendCase(
                news_card_id=None,
                trend_id=trend_id,
                trend_name=data["trend_name"],
                case_title=data["case_title"],
                company=data["company"],
                description=data["description"],
                how_it_works=data.get("how_it_works"),
                value=data["value"],
                market=data["market"],
                source_url=data.get("source_url"),
            )
            s.add(tc)
            s.flush()
            return tc.id

    try:
        case_id = await asyncio.to_thread(_save)
        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "add_case", "case", case_id, {"title": data["case_title"]})
        await state.clear()
        await message.answer(
            f"Кейс #{case_id} добавлен в базу знаний!\n\n"
            f"Тренд: {data['trend_name']}\n"
            f"Кейс: {data['case_title']}"
        )
    except Exception as e:
        logger.error(f"add_case error: {e}")
        await state.clear()
        await message.answer(f"Ошибка при сохранении:\n<code>{e}</code>")


# ── /review_week helpers ───────────────────────────────────────────────────────

def _filters_keyboard(
    current_filter: str, current_sort: str, current_period: int, offset: int
) -> InlineKeyboardMarkup:
    filter_buttons = [
        InlineKeyboardButton(
            text=("✓ " if k == current_filter else "") + label,
            callback_data=f"rw:f:{k}:{current_sort}:{current_period}:0",
        )
        for k, (label, _) in REVIEW_FILTERS.items()
    ]
    sort_buttons = [
        InlineKeyboardButton(
            text=("✓ " if k == current_sort else "") + label,
            callback_data=f"rw:f:{current_filter}:{k}:{current_period}:0",
        )
        for k, label in REVIEW_SORTS.items()
    ]
    period_buttons = [
        InlineKeyboardButton(
            text=("✓ " if k == current_period else "") + label,
            callback_data=f"rw:f:{current_filter}:{current_sort}:{k}:0",
        )
        for k, label in REVIEW_PERIODS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        filter_buttons[:3],
        filter_buttons[3:],
        sort_buttons,
        period_buttons,
    ])


def _get_review_cases(
    filter_key: str, sort_key: str, period_days: int, offset: int
) -> tuple[dict | None, int]:
    from db.base import get_session
    from db.models import NewsCard, Trend, TrendCase

    with get_session() as s:
        q = (
            s.query(TrendCase, NewsCard, Trend)
            .outerjoin(NewsCard, TrendCase.news_card_id == NewsCard.id)
            .outerjoin(Trend, TrendCase.trend_id == Trend.id)
        )

        status = REVIEW_FILTERS[filter_key][1]
        if status == "duplicates":
            q = q.filter(TrendCase.is_duplicate == True)  # noqa: E712
        elif status:
            q = q.filter(NewsCard.review_status == status)

        if period_days > 0:
            since = datetime.utcnow() - timedelta(days=period_days)
            q = q.filter(
                (NewsCard.published_at >= since) | (TrendCase.created_at >= since)
            )

        if sort_key == "score":
            q = q.order_by(NewsCard.relevance_score.desc().nullslast())
        else:
            q = q.order_by(TrendCase.created_at.desc())

        total = q.count()
        row = q.offset(offset).limit(1).first()
        if not row:
            return None, total

        tc, nc, tr = row
        return {
            "id": tc.id,
            "case_title": tc.case_title,
            "company": tc.company,
            "description": tc.description,
            "value": tc.value,
            "market": tc.market,
            "industry": tc.industry,
            "source_url": tc.source_url,
            "is_duplicate": tc.is_duplicate,
            "duplicate_of_case_id": tc.duplicate_of_case_id,
            "trend_name": tr.name if tr else None,
            "trend_status": tr.status if tr else None,
            "review_status": nc.review_status if nc else "manual",
            "score": nc.relevance_score if nc else None,
            "source_title": nc.source_title if nc else None,
            "news_card_id": nc.id if nc else None,
        }, total


def _format_review_case(
    case: dict, current: int, total: int,
    filter_key: str, sort_key: str, period_days: int,
) -> str:
    dup_mark = " 🔁 ДУБЛЬ" if case["is_duplicate"] else ""
    status = case["review_status"] or "—"
    status_icon = {
        "auto": "🔵", "needs_review": "⚠️", "approved": "✅", "rejected": "❌",
    }.get(status, "⚪")
    trend = case["trend_name"] or "<i>без тренда</i>"
    trend_extra = " 🆕" if case["trend_status"] == "pending" else ""
    url_line = f"\n🔗 <a href='{case['source_url']}'>Источник</a>" if case.get("source_url") else ""

    return (
        f"{status_icon} <b>Кейс #{case['id']}</b> ({current}/{total}){dup_mark}\n"
        f"<i>Фильтр: {REVIEW_FILTERS[filter_key][0]} · "
        f"{REVIEW_SORTS[sort_key]} · "
        f"{REVIEW_PERIODS[period_days]}</i>\n\n"
        f"<b>Тренд:</b> {trend}{trend_extra}\n"
        f"<b>Кейс:</b> {case['case_title'] or '—'}\n"
        f"<b>Компания:</b> {case['company'] or '—'} | "
        f"<b>Отрасль:</b> {case['industry'] or '—'} | "
        f"<b>Рынок:</b> {case['market'] or '—'}\n\n"
        f"<b>Описание:</b> {case['description'] or '—'}\n\n"
        f"<b>Ценность:</b> {case['value'] or '—'}"
        f"{url_line}\n\n"
        f"<i>Источник: {case['source_title'] or '—'} | Score: {case['score'] or '—'}</i>\n"
        f"<i>Команда для редактирования: /edit {case['id']}</i>"
    )


def _review_actions_kb(
    case_id: int, filter_key: str, sort_key: str,
    period_days: int, offset: int, total: int,
) -> InlineKeyboardMarkup:
    prefix = f"rw:a:{filter_key}:{sort_key}:{period_days}"
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:prev:{offset}"))
    if offset + 1 < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:next:{offset}"))

    rows = [
        [
            InlineKeyboardButton(text="✅", callback_data=f"{prefix}:approve:{case_id}:{offset}"),
            InlineKeyboardButton(text="❌", callback_data=f"{prefix}:reject:{case_id}:{offset}"),
            InlineKeyboardButton(text="✏️", callback_data=f"{prefix}:edit:{case_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"{prefix}:delete:{case_id}:{offset}"),
        ],
        [InlineKeyboardButton(text="🔧 Фильтры", callback_data=f"rw:menu:{filter_key}:{sort_key}:{period_days}")],
    ]
    if nav_row:
        rows.insert(1, nav_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── /review_week ───────────────────────────────────────────────────────────────

@router.message(Command("review_week"))
@require_role("admin")
async def cmd_review_week(message: Message) -> None:
    case, total = _get_review_cases("all", "score", 7, 0)
    if not case:
        await message.answer(
            "📭 За 7 дней кейсов нет.\n"
            "Текущие фильтры: все, по релевантности, за 7 дней."
        )
        return
    await message.answer(
        _format_review_case(case, 1, total, "all", "score", 7),
        reply_markup=_review_actions_kb(case["id"], "all", "score", 7, 0, total),
        link_preview_options=_NO_PREVIEW,
    )


@router.callback_query(F.data.startswith("rw:menu:"))
async def handle_review_filters_menu(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    filter_key, sort_key, period_days = parts[2], parts[3], int(parts[4])
    await call.message.edit_reply_markup(
        reply_markup=_filters_keyboard(filter_key, sort_key, period_days, 0)
    )
    await call.answer()


@router.callback_query(F.data.startswith("rw:f:"))
async def handle_review_filter_change(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    filter_key, sort_key, period_days, offset = parts[2], parts[3], int(parts[4]), int(parts[5])
    case, total = _get_review_cases(filter_key, sort_key, period_days, offset)
    if not case:
        await call.message.edit_text(
            f"📭 Нет кейсов под фильтром: "
            f"{REVIEW_FILTERS[filter_key][0]} · "
            f"{REVIEW_SORTS[sort_key]} · "
            f"{REVIEW_PERIODS[period_days]}"
        )
        await call.answer()
        return
    await call.message.edit_text(
        _format_review_case(case, offset + 1, total, filter_key, sort_key, period_days),
        reply_markup=_review_actions_kb(case["id"], filter_key, sort_key, period_days, offset, total),
        link_preview_options=_NO_PREVIEW,
    )
    await call.answer()


@router.callback_query(F.data.startswith("rw:a:"))
async def handle_review_action(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    filter_key, sort_key, period_days = parts[2], parts[3], int(parts[4])
    action = parts[5]

    user = get_user_by_tg_id(call.from_user.id)
    if not user or user["role"] != "admin":
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    if action in ("approve", "reject", "delete"):
        case_id = int(parts[6])
        offset = int(parts[7])

        from db.base import get_session
        from db.models import NewsCard, TrendCase

        if action == "delete":
            with get_session() as s:
                tc = s.get(TrendCase, case_id)
                if tc:
                    s.delete(tc)
                    log_action(user["id"], "delete_case", "case", case_id)
            await call.answer("🗑 Удалено")
            new_offset = max(0, offset - 1)
        else:
            new_status = "approved" if action == "approve" else "rejected"
            with get_session() as s:
                tc = s.get(TrendCase, case_id)
                if tc and tc.news_card_id:
                    nc = s.get(NewsCard, tc.news_card_id)
                    if nc:
                        nc.review_status = new_status
                        log_action(user["id"], f"{action}_case", "case", case_id,
                                   {"status": new_status})
            await call.answer("✅ Одобрено" if action == "approve" else "❌ Отклонено")
            new_offset = offset

        case, total = _get_review_cases(filter_key, sort_key, period_days, new_offset)
        if not case:
            await call.message.edit_text("✅ Все кейсы под этим фильтром обработаны.")
        else:
            await call.message.edit_text(
                _format_review_case(case, new_offset + 1, total, filter_key, sort_key, period_days),
                reply_markup=_review_actions_kb(
                    case["id"], filter_key, sort_key, period_days, new_offset, total
                ),
                link_preview_options=_NO_PREVIEW,
            )

    elif action in ("prev", "next"):
        offset = int(parts[6])
        new_offset = offset - 1 if action == "prev" else offset + 1
        case, total = _get_review_cases(filter_key, sort_key, period_days, new_offset)
        if case:
            await call.message.edit_text(
                _format_review_case(case, new_offset + 1, total, filter_key, sort_key, period_days),
                reply_markup=_review_actions_kb(
                    case["id"], filter_key, sort_key, period_days, new_offset, total
                ),
                link_preview_options=_NO_PREVIEW,
            )
        await call.answer()

    elif action == "edit":
        case_id = int(parts[6])
        await state.update_data(editing_case_id=case_id)
        await state.set_state(EditCase.choosing_field)
        buttons = [
            [InlineKeyboardButton(text=v[1], callback_data=f"ef:{k}:{case_id}")]
            for k, v in EDITABLE_FIELDS.items()
        ]
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"ef:cancel:{case_id}")])
        await call.message.answer(
            f"✏️ <b>Редактирование кейса #{case_id}</b>\n\nКакое поле изменить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await call.answer()


# ── /edit <id> ─────────────────────────────────────────────────────────────────

@router.message(Command("edit"))
@require_role("admin")
async def cmd_edit_by_id(message: Message, state: FSMContext) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Использование: /edit &lt;id&gt;\n"
            "ID кейса можно взять из Excel или /review_week"
        )
        return
    try:
        case_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    from db.base import get_session
    from db.models import TrendCase

    with get_session() as s:
        tc = s.get(TrendCase, case_id)
        if not tc:
            await message.answer(f"❌ Кейс #{case_id} не найден.")
            return

    await state.update_data(editing_case_id=case_id)
    await state.set_state(EditCase.choosing_field)
    buttons = [
        [InlineKeyboardButton(text=v[1], callback_data=f"ef:{k}:{case_id}")]
        for k, v in EDITABLE_FIELDS.items()
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"ef:cancel:{case_id}")])
    await message.answer(
        f"✏️ <b>Редактирование кейса #{case_id}</b>\n\nКакое поле изменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
