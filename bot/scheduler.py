import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import FSInputFile, LinkPreviewOptions
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


# ── Вспомогательная функция ───────────────────────────────────────────────────

async def _notify_admins(bot: Bot, text: str) -> None:
    """Отправляет сообщение всем активным админам."""
    from db.base import get_session
    from db.models import BotUser
    with get_session() as s:
        tg_ids = [u.telegram_id for u in s.query(BotUser).filter_by(role="admin", is_active=True).all()]
    for tg_id in tg_ids:
        try:
            await bot.send_message(tg_id, text)
        except Exception as e:
            logger.warning(f"[notify] admin {tg_id} failed: {e}")


# ── Автоматический pipeline ───────────────────────────────────────────────────

async def auto_pipeline_cycle(bot: Bot) -> None:
    """Каждые 30 минут: collect → process → enrich небольшой порцией."""
    logger.info("[auto] Starting pipeline cycle")

    def _collect():
        import asyncio as _aio
        from config.settings import get_settings
        from collector.telegram import TelegramCollector
        settings = get_settings()
        collector = TelegramCollector(settings)

        async def _run():
            await collector.connect()
            try:
                return await collector.collect_all(days=2 / 24)
            finally:
                await collector.disconnect()

        return _aio.run(_run())

    try:
        results = await asyncio.to_thread(_collect)
        total_saved = sum(r.saved for r in results)
        logger.info(f"[auto] collect: saved {total_saved} new posts")
    except Exception as e:
        logger.error(f"[auto] collect failed: {e}")
        await _notify_admins(bot, f"⚠️ Авто-сбор упал: {e}")
        return

    if total_saved == 0:
        logger.info("[auto] No new posts, skipping process/enrich")
        return

    def _process():
        from processor.pipeline import process_raw_posts
        return process_raw_posts()

    try:
        proc_result = await asyncio.to_thread(_process)
        logger.info(f"[auto] process: created {proc_result.created} cards")
    except Exception as e:
        logger.error(f"[auto] process failed: {e}")
        await _notify_admins(bot, f"⚠️ Авто-обработка упала: {e}")
        return

    def _enrich():
        from config.settings import get_settings
        from llm.enricher import enrich_news_cards
        from llm.factory import create_llm_provider
        settings = get_settings()
        provider = create_llm_provider(settings)
        return enrich_news_cards(provider, min_score=settings.llm_min_score, limit=5)

    try:
        enrich_result = await asyncio.to_thread(_enrich)
        logger.info(
            f"[auto] enrich: cases={enrich_result.cases_created} errors={enrich_result.errors}"
        )
    except Exception as e:
        logger.warning(f"[auto] enrich skipped: {e}")

    logger.info("[auto] Pipeline cycle complete")


# ── Пятница 16:00 — база админам на проверку ──────────────────────────────────

async def friday_review_handoff(bot: Bot) -> None:
    """Пятница 16:00 — Excel за неделю всем админам с напоминанием о рассылке в 18:00."""
    logger.info("[scheduler] Friday review handoff")

    def _export():
        from exporter.excel import export_to_excel
        ts = datetime.utcnow().strftime("%Y%m%d")
        return export_to_excel(output_path=f"data/exports/review_{ts}.xlsx")

    try:
        path = await asyncio.to_thread(_export)
    except Exception as e:
        logger.error(f"[scheduler] review export failed: {e}")
        await _notify_admins(bot, f"❌ Не удалось сформировать базу к проверке: {e}")
        return

    from db.base import get_session
    from db.models import BotUser, NewsCard, TrendCase
    from sqlalchemy import or_

    since = datetime.utcnow() - timedelta(days=7)

    with get_session() as s:
        admin_ids = [
            u.telegram_id
            for u in s.query(BotUser).filter_by(role="admin", is_active=True).all()
        ]
        total_cases = (
            s.query(TrendCase)
            .outerjoin(NewsCard, TrendCase.news_card_id == NewsCard.id)
            .filter(or_(NewsCard.published_at >= since, TrendCase.created_at >= since))
            .count()
        )
        needs_review = (
            s.query(TrendCase)
            .join(NewsCard, TrendCase.news_card_id == NewsCard.id)
            .filter(NewsCard.review_status == "needs_review")
            .count()
        )

    caption = (
        "🕘 <b>Вторник, 9:00 — база к проверке</b>\n\n"
        f"За неделю собрано: <b>{total_cases}</b> кейсов\n"
        f"Требуют проверки: <b>{needs_review}</b>\n\n"
        "⏰ Рассылка дайджеста — сегодня в 11:00.\n"
        "У вас 2 часа чтобы проверить базу через /review_week "
        "и отредактировать спорные кейсы."
    )

    for tg_id in admin_ids:
        try:
            await bot.send_document(tg_id, FSInputFile(path), caption=caption)
        except TelegramForbiddenError:
            from db.base import get_session as _gs
            from db.models import BotUser as _BU
            with _gs() as s:
                u = s.query(_BU).filter_by(telegram_id=tg_id).first()
                if u:
                    u.is_active = False
            logger.info(f"[scheduler] Admin tg={tg_id} blocked bot, deactivated")
        except Exception as e:
            logger.warning(f"[scheduler] handoff to admin {tg_id} failed: {e}")

    logger.info(f"[scheduler] Review handoff sent to {len(admin_ids)} admins")


# ── Еженедельный дайджест всем ────────────────────────────────────────────────

async def send_weekly_digest_to_all(bot: Bot) -> None:
    """Пятница 17:00 МСК — генерируем дайджест и рассылаем всем активным пользователям."""
    logger.info("[scheduler] Starting weekly digest broadcast")

    def _generate():
        from config.settings import get_settings
        from digest.generator import generate_digest
        from llm.factory import create_llm_provider

        settings = get_settings()
        provider = create_llm_provider(settings)
        return generate_digest(provider, days=7)

    try:
        result = await asyncio.to_thread(_generate)
    except Exception as e:
        logger.error(f"[scheduler] Failed to generate weekly digest: {e}")
        return

    from db.base import get_session
    from db.models import BotUser

    with get_session() as s:
        tg_ids = [u.telegram_id for u in s.query(BotUser).filter_by(is_active=True).all()]

    path = Path(result.output_path)
    caption = (
        f"<b>Еженедельный финтех-дайджест</b>\n"
        f"Период: {result.period_start.strftime('%d.%m')} — "
        f"{result.period_end.strftime('%d.%m.%Y')}\n"
        f"Кейсов: {result.total_cases} | Тем: {result.topics_count}"
    )

    sent = failed = 0
    for tg_id in tg_ids:
        try:
            await bot.send_document(tg_id, FSInputFile(path), caption=caption)
            sent += 1
            await asyncio.sleep(0.1)
        except TelegramForbiddenError:
            from db.base import get_session
            from db.models import BotUser
            with get_session() as s:
                u = s.query(BotUser).filter_by(telegram_id=tg_id).first()
                if u:
                    u.is_active = False
            logger.info(f"[scheduler] User tg={tg_id} blocked the bot, deactivated")
            failed += 1
        except Exception as e:
            failed += 1
            logger.warning(f"[scheduler] Digest send failed tg={tg_id}: {e}")

    logger.info(f"[scheduler] Weekly digest done: sent={sent} failed={failed}")


# ── Дайджест по подпискам ─────────────────────────────────────────────────────

# ── Запуск планировщика ───────────────────────────────────────────────────────

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    scheduler.add_job(
        auto_pipeline_cycle,
        "interval", minutes=30,
        args=[bot],
        id="auto_pipeline",
        replace_existing=True,
    )
    scheduler.add_job(
        friday_review_handoff,
        CronTrigger(day_of_week="tue", hour=9, minute=0),
        args=[bot],
        id="tuesday_review",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_digest_to_all,
        CronTrigger(day_of_week="tue", hour=11, minute=0),
        args=[bot],
        id="tuesday_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[scheduler] Started:\n"
        "  • auto_pipeline (каждые 30 минут)\n"
        "  • tuesday_review (вт 9:00 МСК — база админам)\n"
        "  • tuesday_digest (вт 11:00 МСК — рассылка всем)"
    )
    return scheduler
