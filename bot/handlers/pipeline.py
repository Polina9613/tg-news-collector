import asyncio
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from loguru import logger

from bot.audit import log_action
from bot.permissions import require_role
from bot.users import get_user_by_tg_id

router = Router()


# ─── /stats ───────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
@require_role("admin", "analyst")
async def cmd_stats(message: Message) -> None:
    """Статистика базы данных."""
    from db.init_db import get_db_stats

    stats = await asyncio.to_thread(get_db_stats)

    by_status = stats.get("by_status", {})
    status_lines = "\n".join(f"  {k}: {v}" for k, v in by_status.items()) or "  —"

    await message.answer(
        "<b>Статистика базы данных</b>\n\n"
        f"Источников: {stats.get('sources', 0)}\n"
        f"Сырых постов: {stats.get('raw_posts', 0)}\n"
        f"Карточек: {stats.get('news_cards', 0)}\n"
        f"Кейсов: {stats.get('trend_cases', 0)}\n"
        f"Трендов: {stats.get('trends', 0)}\n\n"
        f"По статусу проверки:\n{status_lines}"
    )


# ─── /collect ─────────────────────────────────────────────────────────────────

@router.message(Command("collect"))
@require_role("admin")
async def cmd_collect(message: Message) -> None:
    """Запустить сбор постов. Использование: /collect [дней]"""
    parts = message.text.split()
    try:
        days = int(parts[1]) if len(parts) > 1 else 3
        if days < 1 or days > 30:
            raise ValueError
    except ValueError:
        await message.answer("Использование: /collect [1-30]\nПример: /collect 7")
        return

    await message.answer(f"Запускаю сбор постов за {days} дней...")

    def _collect():
        import asyncio as _asyncio
        from collector.telegram import TelegramCollector
        from config.settings import get_settings

        settings = get_settings()
        collector = TelegramCollector(settings)

        async def _run():
            await collector.connect()
            try:
                return await collector.collect_all(days=days)
            finally:
                await collector.disconnect()

        return _asyncio.run(_run())

    try:
        results = await asyncio.to_thread(_collect)
        total_fetched = sum(r.total_fetched for r in results)
        total_saved = sum(r.saved for r in results)
        total_dupes = sum(r.skipped_duplicate for r in results)
        total_errors = sum(r.errors for r in results)

        lines = ["<b>Сбор завершён</b>\n"]
        for r in results:
            lines.append(f"• {r.channel_username}: +{r.saved} постов")
        lines.append(
            f"\nПолучено {total_fetched} | "
            f"сохранено {total_saved} | "
            f"дублей {total_dupes} | "
            f"ошибок {total_errors}"
        )

        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "collect", payload={"days": days, "saved": total_saved})

        await message.answer("\n".join(lines))

    except Exception as e:
        logger.error(f"collect error: {e}")
        await message.answer(f"Ошибка при сборе:\n<code>{e}</code>")


# ─── /process ─────────────────────────────────────────────────────────────────

@router.message(Command("process"))
@require_role("admin")
async def cmd_process(message: Message) -> None:
    """Обработать сырые посты → карточки."""
    await message.answer("Запускаю обработку постов...")

    def _process():
        from processor.pipeline import process_raw_posts
        return process_raw_posts()

    try:
        result = await asyncio.to_thread(_process)

        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "process", payload={"created": result.created})

        await message.answer(
            "<b>Обработка завершена</b>\n\n"
            f"Создано карточек: {result.created}\n"
            f"Пропущено (пустые): {result.skipped_empty}\n"
            f"Дублей: {result.skipped_duplicate}\n"
            f"Ошибок: {result.errors}"
        )
    except Exception as e:
        logger.error(f"process error: {e}")
        await message.answer(f"Ошибка:\n<code>{e}</code>")


# ─── /enrich ──────────────────────────────────────────────────────────────────

@router.message(Command("enrich"))
@require_role("admin")
async def cmd_enrich(message: Message) -> None:
    """Запустить LLM-обогащение. Использование: /enrich [лимит]"""
    parts = message.text.split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 10
        if limit < 1 or limit > 50:
            raise ValueError
    except ValueError:
        await message.answer("Использование: /enrich [1-50]\nПример: /enrich 15")
        return

    await message.answer(
        f"Запускаю LLM-обогащение (лимит {limit} карточек)...\n"
        "Это может занять несколько минут из-за пауз между запросами."
    )

    def _enrich():
        from config.settings import get_settings
        from llm.enricher import enrich_news_cards
        from llm.factory import create_fallback_provider, create_llm_provider

        settings = get_settings()
        provider = create_llm_provider(settings)
        fallback = create_fallback_provider(settings)

        return enrich_news_cards(
            provider,
            min_score=settings.llm_min_score,
            limit=limit,
            fallback_provider=fallback,
        )

    try:
        result = await asyncio.to_thread(_enrich)

        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "enrich", payload={"cases_created": result.cases_created})

        await message.answer(
            "<b>Обогащение завершено</b>\n\n"
            f"Обработано карточек: {result.total}\n"
            f"Релевантных: {result.relevant}\n"
            f"Нерелевантных: {result.irrelevant}\n"
            f"Кейсов создано: {result.cases_created}\n"
            f"Ошибок: {result.errors}"
        )
    except Exception as e:
        logger.error(f"enrich error: {e}")
        await message.answer(f"Ошибка:\n<code>{e}</code>")


# ─── /digest ──────────────────────────────────────────────────────────────────

@router.message(Command("digest"))
@require_role("admin")
async def cmd_digest(message: Message) -> None:
    """Сгенерировать дайджест. Использование: /digest [дней]"""
    parts = message.text.split()
    try:
        days = int(parts[1]) if len(parts) > 1 else 7
        if days < 1 or days > 90:
            raise ValueError
    except ValueError:
        await message.answer("Использование: /digest [1-90]\nПример: /digest 7")
        return

    await message.answer(f"Генерирую дайджест за {days} дней...")

    def _digest():
        from config.settings import get_settings
        from digest.generator import generate_digest
        from llm.factory import create_llm_provider

        settings = get_settings()
        provider = create_llm_provider(settings)
        return generate_digest(provider, days=days)

    try:
        result = await asyncio.to_thread(_digest)
        path = Path(result.output_path)

        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "digest", payload={"days": days, "cases": result.total_cases})

        await message.answer(
            f"<b>Дайджест готов</b>\n\n"
            f"Период: {result.period_start.strftime('%d.%m')} — "
            f"{result.period_end.strftime('%d.%m.%Y')}\n"
            f"Кейсов: {result.total_cases} | Тем: {result.topics_count}\n\n"
            "Отправляю файл..."
        )
        await message.answer_document(
            FSInputFile(path),
            caption=f"Дайджест финтех-новостей {result.period_end.strftime('%d.%m.%Y')}"
        )
    except Exception as e:
        logger.error(f"digest error: {e}")
        await message.answer(f"Ошибка:\n<code>{e}</code>")


# ─── /export ──────────────────────────────────────────────────────────────────

@router.message(Command("export"))
@require_role("admin", "analyst")
async def cmd_export(message: Message) -> None:
    """Получить Excel-экспорт. Использование: /export [дней|all]"""
    parts = message.text.split()
    days_arg = parts[1] if len(parts) > 1 else "7"

    if days_arg.lower() == "all":
        days = None
        caption_period = "за всё время"
    else:
        try:
            days = int(days_arg)
            if days < 1 or days > 365:
                raise ValueError
            caption_period = f"за {days} дней"
        except ValueError:
            await message.answer(
                "Использование:\n"
                "/export 7 — за 7 дней\n"
                "/export 30 — за 30 дней\n"
                "/export all — всё время"
            )
            return

    await message.answer(f"Формирую Excel {caption_period}...")

    def _export():
        from datetime import datetime as _dt

        from exporter.excel import export_to_excel

        ts = _dt.utcnow().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{days}d" if days else "_all"
        path = f"data/exports/bot_export{suffix}_{ts}.xlsx"
        return export_to_excel(output_path=path, days=days)

    try:
        path = await asyncio.to_thread(_export)
        file_size_mb = Path(path).stat().st_size / (1024 * 1024)

        user = get_user_by_tg_id(message.from_user.id)
        if user:
            log_action(user["id"], "export", payload={"days": days, "size_mb": round(file_size_mb, 2)})

        if file_size_mb > 48:
            await message.answer(
                f"Файл слишком большой ({file_size_mb:.1f} МБ).\n"
                "Используйте /export 30 или /export 7 для меньшего периода."
            )
            return

        await message.answer_document(
            FSInputFile(path),
            caption=(
                f"📊 База знаний финтех-кейсов {caption_period}\n"
                f"Размер: {file_size_mb:.1f} МБ\n\n"
                "Листы:\n"
                "• <b>news_cards</b> — все обработанные новости\n"
                "• <b>trend_cases</b> — структурированные кейсы\n"
                "• <b>trends</b> — база знаний трендов\n"
                "• <b>review</b> — карточки на проверку\n"
                "• <b>raw_posts</b> — исходные посты\n\n"
                "Описание листов и цветов: /excel_guide"
            )
        )
    except Exception as e:
        logger.error(f"export error: {e}")
        await message.answer(f"Ошибка:\n<code>{e}</code>")
