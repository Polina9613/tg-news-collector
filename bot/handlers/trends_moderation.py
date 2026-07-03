from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.audit import log_action
from bot.permissions import require_role
from bot.users import get_user_by_tg_id

router = Router()


class TrendModeration(StatesGroup):
    waiting_for_rename = State()
    waiting_for_merge_id = State()


def _get_pending_trends() -> list[dict]:
    from sqlalchemy import func

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        rows = (
            s.query(Trend, func.count(TrendCase.id).label("cnt"))
            .outerjoin(TrendCase, TrendCase.trend_id == Trend.id)
            .filter(Trend.status == "pending")
            .group_by(Trend.id)
            .order_by(Trend.id.desc())
            .all()
        )
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description or "",
                "category": t.category,
                "cases_count": cnt,
                "proposed_by_case_id": t.proposed_by_case_id,
            }
            for t, cnt in rows
        ]


def _trend_card_text(trend: dict) -> str:
    return (
        f"🆕 <b>Pending тренд #{trend['id']}</b>\n\n"
        f"<b>Название:</b> {trend['name']}\n"
        f"<b>Кейсов под трендом:</b> {trend['cases_count']}\n\n"
        f"<b>Описание:</b>\n<i>{trend['description']}</i>\n\n"
        f"Предложен по кейсу #{trend['proposed_by_case_id'] or '—'}"
    )


def _trend_actions_kb(trend_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"pt:approve:{trend_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pt:reject:{trend_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"pt:rename:{trend_id}"),
            InlineKeyboardButton(text="↔️ Объединить", callback_data=f"pt:merge:{trend_id}"),
        ],
    ])


@router.message(Command("pending_trends"))
@require_role("admin")
async def cmd_pending_trends(message: Message) -> None:
    pending = _get_pending_trends()
    if not pending:
        await message.answer("✅ Pending трендов нет — все одобрены или отклонены.")
        return

    await message.answer(
        f"📋 На модерации <b>{len(pending)}</b> предложенных трендов.\n\n"
        "Действия по каждому:\n"
        "✅ Одобрить — тренд станет active\n"
        "❌ Отклонить — кейсы отвяжутся, тренд получит статус rejected\n"
        "✏️ Переименовать — изменить название\n"
        "↔️ Объединить — слить с существующим трендом"
    )
    for trend in pending:
        await message.answer(
            _trend_card_text(trend),
            reply_markup=_trend_actions_kb(trend["id"]),
        )


@router.callback_query(F.data.startswith("pt:approve:"))
async def handle_approve_trend(call: CallbackQuery) -> None:
    user = get_user_by_tg_id(call.from_user.id)
    if not user or user["role"] != "admin":
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    trend_id = int(call.data.split(":")[2])
    from db.base import get_session
    from db.models import Trend

    with get_session() as s:
        trend = s.get(Trend, trend_id)
        if not trend:
            await call.answer("❌ Тренд не найден", show_alert=True)
            return
        trend_name = trend.name
        trend.status = "active"
        log_action(user["id"], "approve_trend", "trend", trend_id, {"name": trend_name})

    from llm.enricher import _load_active_trends
    _load_active_trends(force_refresh=True)

    await call.message.edit_text(
        f"✅ <b>Одобрен:</b> {trend_name}\n"
        "Тренд переведён в active и доступен для новых кейсов."
    )
    await call.answer("Одобрен")


@router.callback_query(F.data.startswith("pt:reject:"))
async def handle_reject_trend(call: CallbackQuery) -> None:
    user = get_user_by_tg_id(call.from_user.id)
    if not user or user["role"] != "admin":
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    trend_id = int(call.data.split(":")[2])
    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        trend = s.get(Trend, trend_id)
        if not trend:
            await call.answer("❌ Тренд не найден", show_alert=True)
            return
        trend_name = trend.name
        affected = s.query(TrendCase).filter_by(trend_id=trend_id).update({"trend_id": None})
        trend.status = "rejected"
        log_action(user["id"], "reject_trend", "trend", trend_id,
                   {"name": trend_name, "cases_unlinked": affected})

    await call.message.edit_text(
        f"❌ <b>Отклонён:</b> {trend_name}\n"
        f"Отвязано кейсов: {affected}. Кейсы остались в базе без тренда."
    )
    await call.answer("Отклонён")


@router.callback_query(F.data.startswith("pt:rename:"))
async def handle_rename_trend(call: CallbackQuery, state: FSMContext) -> None:
    user = get_user_by_tg_id(call.from_user.id)
    if not user or user["role"] != "admin":
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    trend_id = int(call.data.split(":")[2])
    await state.update_data(trend_id=trend_id)
    await state.set_state(TrendModeration.waiting_for_rename)
    await call.message.answer(
        f"✏️ Введите новое название для тренда #{trend_id}\n"
        "Или /cancel чтобы отменить."
    )
    await call.answer()


@router.message(TrendModeration.waiting_for_rename)
async def handle_rename_input(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    new_name = message.text.strip()
    if len(new_name) < 3 or len(new_name) > 80:
        await message.answer("Название должно быть от 3 до 80 символов. Введите ещё раз или /cancel.")
        return

    data = await state.get_data()
    trend_id = data["trend_id"]
    user = get_user_by_tg_id(message.from_user.id)

    from db.base import get_session
    from db.models import Trend

    with get_session() as s:
        trend = s.get(Trend, trend_id)
        if not trend:
            await message.answer("❌ Тренд не найден.")
            await state.clear()
            return
        old_name = trend.name
        trend.name = new_name
        trend.status = "active"
        log_action(user["id"], "rename_trend", "trend", trend_id, {"old": old_name, "new": new_name})

    await message.answer(
        f"✅ Переименован и активирован:\n"
        f"<s>{old_name}</s> → <b>{new_name}</b>"
    )
    await state.clear()


@router.callback_query(F.data.startswith("pt:merge:"))
async def handle_merge_trend(call: CallbackQuery, state: FSMContext) -> None:
    user = get_user_by_tg_id(call.from_user.id)
    if not user or user["role"] != "admin":
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    trend_id = int(call.data.split(":")[2])
    await state.update_data(merge_from_id=trend_id)
    await state.set_state(TrendModeration.waiting_for_merge_id)

    from db.base import get_session
    from db.models import Trend

    with get_session() as s:
        active = (
            s.query(Trend)
            .filter_by(status="active")
            .order_by(Trend.category, Trend.name)
            .all()
        )
        lines = [f"#{t.id} {t.name}" for t in active]

    await call.message.answer(
        f"↔️ Введите ID существующего тренда, в который объединить тренд #{trend_id}:\n\n"
        + "\n".join(lines[:30])
        + "\n\nИли /cancel"
    )
    await call.answer()


@router.message(TrendModeration.waiting_for_merge_id)
async def handle_merge_input(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    try:
        target_id = int(message.text.strip().lstrip("#"))
    except ValueError:
        await message.answer("Введите число — ID тренда. Или /cancel.")
        return

    data = await state.get_data()
    from_id = data["merge_from_id"]
    user = get_user_by_tg_id(message.from_user.id)

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        source = s.get(Trend, from_id)
        target = s.get(Trend, target_id)
        if not source or not target:
            await message.answer("❌ Один из трендов не найден.")
            await state.clear()
            return
        if target.status != "active":
            await message.answer("❌ Целевой тренд должен быть active. Выберите другой.")
            return
        source_name = source.name
        target_name = target.name
        moved = s.query(TrendCase).filter_by(trend_id=from_id).update({"trend_id": target_id})
        source.status = "rejected"
        log_action(user["id"], "merge_trend", "trend", from_id,
                   {"merged_into": target_id, "cases_moved": moved})

    await message.answer(
        f"✅ Объединено:\n"
        f"<b>{source_name}</b> → <b>{target_name}</b>\n"
        f"Перенесено кейсов: {moved}"
    )
    await state.clear()
