import asyncio
import sys
from datetime import datetime
from pathlib import Path

import typer
from loguru import logger
from pydantic import ValidationError

from collector.telegram import CollectResult, TelegramCollector
from config.settings import Settings, get_settings, setup_logging
from db.init_db import get_db_stats, init_db
from exporter.excel import export_to_excel
from processor.pipeline import ProcessResult, process_raw_posts

app = typer.Typer(
    name="tg-news",
    help="Сбор и обработка новостей из Telegram-каналов",
    add_completion=False,
)

# --- Internal helpers ---------------------------------------------------------

_SEP = "─" * 44


def _safe_setup_logging() -> None:
    """Инициализирует loguru; при ошибке конфигурации использует дефолтный INFO."""
    try:
        setup_logging()
    except Exception:
        logger.remove()
        logger.add(
            sys.stderr,
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        )


async def _run_collect(
    settings: Settings,
    days: int,
    channel: str | None,
) -> list[CollectResult]:
    collector = TelegramCollector(settings)
    await collector.connect()
    try:
        if channel:
            result = await collector.collect_channel(channel, days=days)
            return [result]
        return await collector.collect_all(days=days)
    finally:
        await collector.disconnect()


def _print_collect_table(results: list[CollectResult]) -> None:
    if not results:
        typer.echo("Нет результатов")
        return
    widths = [22, 10, 11, 7, 11, 8]
    headers = ["Канал", "Получено", "Сохранено", "Дубли", "Пропущено", "Ошибки"]
    typer.echo("".join(h.ljust(w) for h, w in zip(headers, widths)))
    typer.echo("─" * sum(widths))
    tf = ts = td = te = ter = 0
    for r in results:
        row = [
            f"@{r.channel_username}",
            str(r.total_fetched), str(r.saved),
            str(r.skipped_duplicate), str(r.skipped_empty), str(r.errors),
        ]
        typer.echo("".join(v.ljust(w) for v, w in zip(row, widths)))
        tf += r.total_fetched
        ts += r.saved
        td += r.skipped_duplicate
        te += r.skipped_empty
        ter += r.errors
    typer.echo("─" * sum(widths))
    totals = ["Итого:", str(tf), str(ts), str(td), str(te), str(ter)]
    typer.echo("".join(v.ljust(w) for v, w in zip(totals, widths)))


def _print_stats(stats: dict) -> None:
    typer.echo(f"── Статистика базы данных {'─' * 18}")
    typer.echo(f"  {'Источников:':<22}{stats.get('sources', 0)}")
    typer.echo(f"  {'Сырых постов:':<22}{stats.get('raw_posts', 0)}")
    typer.echo(f"  {'Карточек новостей:':<22}{stats.get('news_cards', 0)}")
    by_status = stats.get("by_status", {})
    if by_status:
        typer.echo("")
        typer.echo("  По статусу проверки:")
        for status, count in by_status.items():
            label = f"{status}:"
            typer.echo(f"    {label:<20}{count}")
    typer.echo(_SEP)


def _require_telegram_settings() -> Settings:
    """Загружает Settings или завершает CLI с понятным сообщением об ошибке."""
    try:
        return get_settings()
    except ValidationError:
        typer.echo(
            "✗ Ошибка конфигурации: заполните .env файл"
            " (TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)"
        )
        raise typer.Exit(code=1)


def _check_sources_file(path: str) -> None:
    """Завершает CLI если sources.yaml не найден."""
    if not Path(path).exists():
        typer.echo(
            f"✗ Файл {path} не найден."
            f" Скопируйте sources.example.yaml → {path} и заполните его."
        )
        raise typer.Exit(code=1)


# --- Commands -----------------------------------------------------------------


@app.command("init-db")
def init_db_cmd() -> None:
    """Инициализировать базу данных (создать таблицы)."""
    _safe_setup_logging()
    init_db()
    typer.echo("✓ База данных инициализирована")
    _print_stats(get_db_stats())


@app.command()
def collect(
    days: int | None = typer.Option(None, "--days", help="За сколько дней собирать"),
    channel: str | None = typer.Option(
        None, "--channel", help="Один канал (@bankiros_ru); без флага — все из sources.yaml"
    ),
) -> None:
    """Собрать посты из Telegram-каналов."""
    _safe_setup_logging()
    settings = _require_telegram_settings()
    if days is None:
        days = settings.default_collect_days
    if not channel:
        _check_sources_file(settings.sources_file)
    try:
        results = asyncio.run(_run_collect(settings, days, channel))
    except Exception as e:
        typer.echo(f"✗ Ошибка подключения к Telegram: {e}")
        raise typer.Exit(code=1)
    _print_collect_table(results)


@app.command()
def process(
    since: str | None = typer.Option(
        None, "--since", help="Обрабатывать посты начиная с (YYYY-MM-DD)"
    ),
) -> None:
    """Обработать собранные посты и создать карточки новостей."""
    _safe_setup_logging()
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d")
        except ValueError:
            typer.echo(f"✗ Неверный формат даты: {since!r}. Используйте YYYY-MM-DD")
            raise typer.Exit(code=1)
    result: ProcessResult = process_raw_posts(since=since_dt)
    typer.echo("✓ Обработка завершена")
    typer.echo(f"  {'Всего постов:':<22}{result.total}")
    typer.echo(f"  {'Создано карточек:':<22}{result.created}")
    typer.echo(f"  {'Пропущено (дубли):':<22}{result.skipped_duplicate}")
    typer.echo(f"  {'Пропущено (пустые):':<22}{result.skipped_empty}")
    typer.echo(f"  {'Ошибки:':<22}{result.errors}")


@app.command()
def reprocess() -> None:
    """Пересчитать все карточки заново (после изменения логики процессора)."""
    _safe_setup_logging()
    from processor.pipeline import reprocess_all_cards
    typer.echo("Удаляем старые карточки и пересчитываем...")
    result = reprocess_all_cards()
    typer.echo(f"""
✓ Пересчёт завершён
  Создано карточек:     {result.created}
  Пропущено (пустые):   {result.skipped_empty}
  Ошибки:               {result.errors}
""")


@app.command()
def export(
    output: str | None = typer.Option(None, "--output", help="Путь к .xlsx файлу"),
) -> None:
    """Экспортировать данные из БД в Excel."""
    _safe_setup_logging()
    path = export_to_excel(output_path=output)
    typer.echo(f"✓ Экспорт завершён: {path}")


@app.command("run-daily")
def run_daily(
    days: int = typer.Option(1, "--days", help="За сколько дней собирать"),
) -> None:
    """Полный цикл: сбор → обработка → экспорт."""
    _safe_setup_logging()
    settings = _require_telegram_settings()
    _check_sources_file(settings.sources_file)

    typer.echo(f"[1/3] Сбор постов за {days} {'день' if days == 1 else 'дней'}...")
    try:
        results = asyncio.run(_run_collect(settings, days, None))
    except Exception as e:
        typer.echo(f"✗ Ошибка подключения к Telegram: {e}")
        raise typer.Exit(code=1)
    for r in results:
        typer.echo(f"  @{r.channel_username}: {r.saved} новых постов")

    typer.echo("[2/3] Обработка...")
    proc_result: ProcessResult = process_raw_posts()
    typer.echo(f"  Создано карточек: {proc_result.created}")

    typer.echo("[3/3] Экспорт...")
    path = export_to_excel()
    typer.echo(f"  Файл: {path}")
    typer.echo("✓ Готово")


@app.command()
def enrich(
    limit: int = typer.Option(30, help="Макс. карточек за запуск"),
    min_score: int = typer.Option(20, help="Мин. score для обогащения"),
    reprocess: bool = typer.Option(False, "--reprocess", help="Повторно обработать"),
) -> None:
    """Структурировать карточки через LLM (Groq) → trend_cases."""
    _safe_setup_logging()
    settings = get_settings()
    from llm.groq_provider import GroqProvider
    from llm.enricher import enrich_news_cards

    if not settings.llm_api_key:
        typer.echo("✗ Не задан LLM_API_KEY в .env")
        raise typer.Exit(code=1)

    provider = GroqProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
    )

    if not provider.is_available():
        typer.echo("✗ Groq API недоступен. Проверьте LLM_API_KEY и соединение.")
        raise typer.Exit(code=1)

    typer.echo(f"Модель: {settings.llm_model} | Лимит: {limit} карточек")
    result = enrich_news_cards(provider, min_score=min_score, limit=limit, reprocess=reprocess)

    typer.echo(f"""
✓ Обогащение завершено
  Обработано:       {result.total}
  Релевантных:      {result.relevant}
  Нерелевантных:    {result.irrelevant}
  Кейсов создано:   {result.cases_created}
  Ошибки:           {result.errors}
""")
    if result.error_messages:
        for msg in result.error_messages[:5]:
            typer.echo(f"  ! {msg}")


@app.command(name="enrich-all")
def enrich_all(
    min_score: int = typer.Option(25, help="Мин. score для обогащения"),
    batch_size: int = typer.Option(10, help="Карточек за один батч"),
    pause: int = typer.Option(120, help="Пауза между батчами (секунд)"),
    reprocess: bool = typer.Option(False, "--reprocess", help="Повторно обработать уже обогащённые"),
) -> None:
    """Обогатить ВСЕ необработанные карточки батчами с паузами между ними."""
    import math
    import time

    _safe_setup_logging()
    settings = get_settings()

    if not settings.llm_api_key:
        typer.echo("✗ Не задан LLM_API_KEY в .env")
        raise typer.Exit(code=1)

    from db.base import get_session
    from db.models import NewsCard
    from llm.enricher import enrich_news_cards
    from llm.groq_provider import GroqProvider

    provider = GroqProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
    )

    if not provider.is_available():
        typer.echo("✗ Groq API недоступен. Проверьте LLM_API_KEY.")
        raise typer.Exit(code=1)

    def count_pending() -> int:
        with get_session() as s:
            q = s.query(NewsCard).filter(NewsCard.relevance_score >= min_score)
            if not reprocess:
                q = q.filter(NewsCard.llm_enriched == False)  # noqa: E712
            return q.count()

    total_pending = count_pending()
    if total_pending == 0:
        typer.echo("✓ Нет карточек для обработки.")
        return

    total_batches = math.ceil(total_pending / batch_size)
    est_minutes = round(total_pending * 10 / 60)

    typer.echo(f"""
── Обогащение всех карточек ────────────────────────
  Необработанных:   {total_pending}
  Батчей:           {total_batches}
  Размер батча:     {batch_size}
  Пауза:            {pause} сек между батчами
  Примерное время:  ~{est_minutes} мин
────────────────────────────────────────────────────
""")

    total_relevant = 0
    total_irrelevant = 0
    total_cases = 0
    total_errors = 0
    batch_num = 0

    while True:
        remaining = count_pending()
        if remaining == 0:
            break

        batch_num += 1
        typer.echo(f"[Батч {batch_num}/{total_batches}] осталось карточек: {remaining}")

        result = enrich_news_cards(
            provider,
            min_score=min_score,
            limit=batch_size,
            reprocess=reprocess,
        )

        total_relevant += result.relevant
        total_irrelevant += result.irrelevant
        total_cases += result.cases_created
        total_errors += result.errors

        typer.echo(
            f"  → релевантных: {result.relevant} | "
            f"нерелевантных: {result.irrelevant} | "
            f"кейсов: {result.cases_created} | "
            f"ошибок: {result.errors}"
        )

        if count_pending() == 0:
            break

        typer.echo(f"  Пауза {pause} сек перед следующим батчем...")
        elapsed = 0
        while elapsed < pause:
            time.sleep(min(30, pause - elapsed))
            elapsed += 30
            if elapsed < pause:
                typer.echo(f"  ... ещё {pause - elapsed} сек")

    typer.echo(f"""
✓ Готово
────────────────────────────────────────────────────
  Батчей обработано:   {batch_num}
  Релевантных:         {total_relevant}
  Нерелевантных:       {total_irrelevant}
  Кейсов создано:      {total_cases}
  Ошибок:              {total_errors}
────────────────────────────────────────────────────
""")


@app.command()
def digest(
    days: int = typer.Option(7, help="За сколько дней формировать дайджест"),
    max_cases: int = typer.Option(15, help="Максимум кейсов"),
    output: str | None = typer.Option(None, help="Путь к файлу (по умолчанию data/digests/)"),
) -> None:
    """Сгенерировать Word-дайджест за период."""
    _safe_setup_logging()
    settings = get_settings()
    from llm.groq_provider import GroqProvider
    from digest.generator import generate_digest

    if not settings.llm_api_key:
        typer.echo("✗ Не задан LLM_API_KEY в .env")
        raise typer.Exit(code=1)

    provider = GroqProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
    )

    if not provider.is_available():
        typer.echo("✗ Groq API недоступен. Проверьте LLM_API_KEY.")
        raise typer.Exit(code=1)

    typer.echo(f"Генерация дайджеста за {days} дней (макс. {max_cases} кейсов)...")
    result = generate_digest(provider, days=days, output_path=output, max_cases=max_cases)

    typer.echo(f"""
✓ Дайджест готов
  Период:    {result.period_start.strftime('%d.%m.%Y')} – {result.period_end.strftime('%d.%m.%Y')}
  Кейсов:    {result.total_cases}
  Тем:       {result.topics_count}
  Файл:      {result.output_path}
""")


@app.command()
def trends() -> None:
    """Показать список трендов в базе знаний."""
    _safe_setup_logging()
    from sqlalchemy import func

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as session:
        rows = (
            session.query(
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
                row.id,
                row.name,
                row.first_seen_at.strftime("%b %Y") if row.first_seen_at else "—",
                row.cnt,
            )
            for row in rows
        ]

    if not data:
        typer.echo("Трендов нет. Запустите: python -m cli enrich")
        return

    SEP = "─" * 56
    typer.echo(f"── Тренды в базе знаний {'─' * 30}")
    typer.echo(f"  {'ID':<4} {'Тренд':<32} {'Кейсов':<8} {'Первый кейс'}")
    typer.echo(SEP)
    for tid, name, first, cnt in data:
        typer.echo(f"  {tid:<4} {name[:32]:<32} {cnt:<8} {first}")
    typer.echo(SEP)


@app.command()
def search(
    query: str | None = typer.Option(None, "--query", help="Поиск по тексту кейса"),
    company: str | None = typer.Option(None, "--company", help="Фильтр по компании"),
    trend_id: int | None = typer.Option(None, "--trend-id", help="Фильтр по ID тренда"),
    period: str | None = typer.Option(None, "--period", help="Период (например 2026-Q2)"),
) -> None:
    """Поиск по базе кейсов (LIKE по тексту, компании, тренду, периоду)."""
    _safe_setup_logging()
    from sqlalchemy import or_

    from db.base import get_session
    from db.models import TrendCase

    with get_session() as session:
        q = session.query(TrendCase)
        if query:
            q = q.filter(
                or_(
                    TrendCase.case_title.like(f"%{query}%"),
                    TrendCase.description.like(f"%{query}%"),
                    TrendCase.trend_name.like(f"%{query}%"),
                )
            )
        if company:
            q = q.filter(TrendCase.company.like(f"%{company}%"))
        if trend_id is not None:
            q = q.filter(TrendCase.trend_id == trend_id)
        if period:
            q = q.filter(TrendCase.period_label == period)

        results = q.order_by(TrendCase.id.desc()).limit(20).all()
        rows = [
            {
                "period": tc.period_label or "—",
                "trend": tc.trend_name or "—",
                "case_title": tc.case_title or "—",
                "company": tc.company or "—",
                "market": tc.market or "—",
                "description": (tc.description or "")[:150],
                "source_url": tc.source_url or "",
            }
            for tc in results
        ]

    if not rows:
        typer.echo("Ничего не найдено.")
        return

    typer.echo(f"Найдено: {len(rows)} кейсов\n")
    for r in rows:
        typer.echo(f"[{r['period']}] {r['trend']}")
        typer.echo(f"  Кейс: {r['case_title']}")
        typer.echo(f"  Компания: {r['company']} | Рынок: {r['market']}")
        if r["description"]:
            typer.echo(f"  Описание: {r['description']}")
        if r["source_url"]:
            typer.echo(f"  Ссылка: {r['source_url']}")
        typer.echo("")


@app.command("trend-info")
def trend_info(
    id: int = typer.Option(..., "--id", help="ID тренда"),
) -> None:
    """Детальная информация по тренду."""
    _safe_setup_logging()
    from collections import Counter

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as session:
        trend = session.get(Trend, id)
        if not trend:
            typer.echo(f"✗ Тренд id={id} не найден")
            raise typer.Exit(code=1)
        cases = session.query(TrendCase).filter(TrendCase.trend_id == id).all()
        period_counter = Counter(c.period_label for c in cases if c.period_label)
        companies = sorted({c.company for c in cases if c.company})
        market_counter = Counter(c.market for c in cases if c.market)
        cases_count = len(cases)
        name = trend.name
        desc = trend.description or ""
        first_seen = trend.first_seen_at

    SEP = "─" * 50

    def _plural(n: int) -> str:
        if 11 <= n % 100 <= 14:
            return "кейсов"
        r = n % 10
        if r == 1:
            return "кейс"
        if 2 <= r <= 4:
            return "кейса"
        return "кейсов"

    typer.echo(f"── Тренд: {name} {'─' * max(0, 40 - len(name))}")
    if desc:
        typer.echo(f"  Описание: {desc}")
    typer.echo(f"  Первый кейс: {first_seen.strftime('%d %B %Y') if first_seen else '—'}")
    typer.echo(f"  Всего кейсов: {cases_count}")

    if period_counter:
        typer.echo("\n  Кейсы по периодам:")
        for p, cnt in sorted(period_counter.items()):
            typer.echo(f"    {p}: {cnt} {_plural(cnt)}")

    if companies:
        typer.echo(f"\n  Компании: {', '.join(companies[:10])}")

    if market_counter:
        parts = [f"{m} ({cnt})" for m, cnt in market_counter.items()]
        typer.echo(f"  Рынки: {', '.join(parts)}")

    typer.echo(SEP)


@app.command()
def stats() -> None:
    """Показать статистику базы данных."""
    _safe_setup_logging()
    _print_stats(get_db_stats())
