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
    days: int | None = typer.Option(None, "--days", "-d", help="За сколько дней (по умолчанию — всё время)"),
) -> None:
    """Экспортировать данные из БД в Excel."""
    _safe_setup_logging()
    path = export_to_excel(output_path=output, days=days)
    typer.echo(f"✓ Экспорт завершён: {path}")


@app.command("collect-rss")
def collect_rss_cmd(
    days: float = typer.Option(7.0, "--days", "-d", help="За сколько дней собирать"),
) -> None:
    """Собрать статьи из RSS-лент (из rss_sources в sources.yaml)."""
    _safe_setup_logging()
    settings = get_settings()
    _check_sources_file(settings.sources_file)

    from collector.rss_pipeline import collect_rss_all

    results = collect_rss_all(days=days)
    if not results:
        typer.echo("Нет активных RSS-источников.")
        return

    total = sum(r.saved for r in results)
    typer.echo("RSS-сбор завершён:")
    for r in results:
        typer.echo(
            f"  {r.source_username}: "
            f"+{r.saved} новых | дублей {r.skipped_duplicate} | "
            f"пустых {r.skipped_empty} | ошибок {r.errors}"
        )
    typer.echo(f"\nИтого: {total} новых статей")


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
    """Структурировать карточки через LLM → trend_cases."""
    _safe_setup_logging()
    settings = get_settings()
    from llm.enricher import enrich_news_cards
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации LLM: {e}")
        raise typer.Exit(code=1)

    if not provider.is_available():
        typer.echo(f"✗ {settings.llm_provider} недоступен — проверьте настройки.")
        raise typer.Exit(code=1)

    typer.echo(f"Провайдер: {settings.llm_provider} | Модель: {settings.llm_model} | Лимит: {limit} карточек")
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

    from db.base import get_session
    from db.models import NewsCard
    from llm.enricher import enrich_news_cards
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации LLM: {e}")
        raise typer.Exit(code=1)

    if not provider.is_available():
        typer.echo(f"✗ {settings.llm_provider} недоступен — проверьте настройки.")
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


@app.command(name="enrich-backlog")
def enrich_backlog_cmd(
    batch_size: int = typer.Option(20, "--batch-size", "-b", help="Карточек за одну порцию"),
    max_batches: int = typer.Option(10, "--max-batches", "-n", help="Сколько порций обработать"),
    pause_seconds: int = typer.Option(30, "--pause", help="Пауза между порциями (секунд)"),
    min_score: int = typer.Option(20, "--min-score", help="Мин. score для обогащения"),
) -> None:
    """Разгрести очередь необработанных карточек порциями с паузами между ними.

    Останавливается если очередь пуста или достигнут max_batches.
    """
    import time as _time

    _safe_setup_logging()
    settings = get_settings()

    from llm.enricher import enrich_news_cards
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации LLM: {e}")
        raise typer.Exit(code=1)

    if not provider.is_available():
        typer.echo(f"✗ {settings.llm_provider} недоступен — проверьте настройки.")
        raise typer.Exit(code=1)

    total_cases = 0
    total_errors = 0

    for batch_num in range(1, max_batches + 1):
        typer.echo(f"\n── Порция {batch_num}/{max_batches} ──")
        result = enrich_news_cards(provider, min_score=min_score, limit=batch_size)

        typer.echo(
            f"  relevant={result.relevant} irrelevant={result.irrelevant} "
            f"news_only={result.news_only} digest_only={result.digest_only} "
            f"cases={result.cases_created} errors={result.errors}"
        )
        total_cases += result.cases_created
        total_errors += result.errors

        if result.total == 0:
            typer.echo("Очередь пуста, останавливаюсь.")
            break

        if batch_num < max_batches:
            typer.echo(f"  Пауза {pause_seconds} сек...")
            _time.sleep(pause_seconds)

    typer.echo(f"\n✓ Итого: cases_created={total_cases}, errors={total_errors}")


@app.command()
def digest(
    days: int = typer.Option(7, help="За сколько дней формировать дайджест"),
    max_cases: int = typer.Option(15, help="Максимум кейсов"),
    output: str | None = typer.Option(None, help="Путь к файлу (по умолчанию data/digests/)"),
) -> None:
    """Сгенерировать Word-дайджест за период."""
    _safe_setup_logging()
    settings = get_settings()
    from digest.generator import generate_digest
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации LLM: {e}")
        raise typer.Exit(code=1)

    if not provider.is_available():
        typer.echo(f"✗ {settings.llm_provider} недоступен — проверьте настройки.")
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


@app.command(name="backfill-snapshots")
def backfill_snapshots_cmd(
    weeks: int = typer.Option(2, "--weeks", "-w", help="За сколько недель назад восстановить снимки"),
) -> None:
    """Восстановить WeeklySnapshot за последние N недель с LLM-анализом.

    Использует кейсы уже накопленные в БД. Пропускает недели для которых
    снимок уже существует. Дальше снимки сохраняются автоматически при
    каждой генерации /digest.
    """
    import json
    from datetime import timedelta

    _safe_setup_logging()
    settings = get_settings()

    from db.base import get_session
    from db.models import NewsCard, Trend, TrendCase, WeeklySnapshot
    from digest.generator import _group_by_topic
    from digest.llm_digest import generate_digest_analysis
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации LLM: {e}")
        raise typer.Exit(code=1)

    if not provider.is_available():
        typer.echo(f"✗ {settings.llm_provider} недоступен — проверьте настройки.")
        raise typer.Exit(code=1)

    now = datetime.utcnow()
    created = 0
    skipped = 0

    # От старых недель к новым — чтобы при генерации динамики для недели N-1
    # уже был снимок недели N-2
    week_ranges = []
    for week_offset in range(weeks, 0, -1):
        period_end = now - timedelta(days=7 * (week_offset - 1))
        period_start = period_end - timedelta(days=7)
        week_ranges.append((period_start, period_end))

    typer.echo(f"Backfill снимков за {weeks} недели назад...\n")

    for period_start, period_end in week_ranges:
        with get_session() as s:
            existing = (
                s.query(WeeklySnapshot)
                .filter(WeeklySnapshot.period_start >= period_start - timedelta(hours=12))
                .filter(WeeklySnapshot.period_start <= period_start + timedelta(hours=12))
                .first()
            )
            if existing:
                skipped += 1
                typer.echo(
                    f"  Неделя {period_start.date()}–{period_end.date()}: снимок уже есть, пропуск"
                )
                continue

            rows = (
                s.query(TrendCase, NewsCard, Trend)
                .outerjoin(NewsCard, TrendCase.news_card_id == NewsCard.id)
                .outerjoin(Trend, TrendCase.trend_id == Trend.id)
                .filter(
                    ((NewsCard.published_at >= period_start) & (NewsCard.published_at < period_end))
                    | ((TrendCase.created_at >= period_start) & (TrendCase.created_at < period_end))
                )
                .filter(TrendCase.is_duplicate == False)  # noqa: E712
                .all()
            )

            if not rows:
                typer.echo(
                    f"  Неделя {period_start.date()}–{period_end.date()}: нет кейсов, пропуск"
                )
                continue

            cases = []
            for tc, nc, trend in rows:
                topic_category = (trend.category if trend else None) or tc.industry or "Другое"
                cases.append({
                    "case_title": tc.case_title,
                    "company": tc.company,
                    "description": tc.description,
                    "how_it_works": tc.how_it_works,
                    "value": tc.value,
                    "market": tc.market,
                    "industry": tc.industry,
                    "source_url": tc.source_url,
                    "trend_name": trend.name if trend else None,
                    "trend_category": topic_category,
                    "relevance_score": nc.relevance_score if nc else 0,
                })

        topics = _group_by_topic(cases)
        top_cases_for_context = sorted(
            cases, key=lambda c: c.get("relevance_score", 0), reverse=True
        )[:15]

        typer.echo(
            f"  Неделя {period_start.date()}–{period_end.date()}: "
            f"{len(cases)} кейсов, запрашиваю LLM-анализ..."
        )
        analysis = generate_digest_analysis(provider, top_cases_for_context, topics)

        compact_index = [
            {
                "company": c.get("company") or "—",
                "topic": topic,
                "title": (c.get("case_title") or "")[:100],
            }
            for topic, tcases in topics.items()
            for c in tcases
        ]

        with get_session() as s:
            s.add(WeeklySnapshot(
                period_start=period_start,
                period_end=period_end,
                main_summary=analysis.get("main_summary", ""),
                overall_conclusions=json.dumps(
                    analysis.get("overall_conclusions", []), ensure_ascii=False
                ),
                compact_case_index=json.dumps(compact_index, ensure_ascii=False),
            ))
        created += 1
        typer.echo(
            f"    Сохранено: {len(compact_index)} кейсов, "
            f"{len(analysis.get('overall_conclusions', []))} выводов"
        )

    typer.echo(f"\n Готово: создано {created} снимков, пропущено {skipped}")


@app.command(name="clean-source-duplicates")
def clean_source_duplicates_cmd(
    days: int = typer.Option(30, "--days", "-d", help="За сколько дней назад проверить"),
    min_cases_per_url: int = typer.Option(3, "--min", help="Мин. кейсов на URL для проверки"),
    max_generic_ratio: float = typer.Option(
        0.7, "--max-generic-ratio",
        help="Мин. доля кейсов БЕЗ конкретной компании чтобы считать URL подозрительным",
    ),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Только показать, не применять"),
) -> None:
    """Найти source_url где большинство кейсов без компании — признак раздробленного обзора.

    НЕ трогает агрегаторы/сводки где кейсы имеют разные реальные компании.
    По умолчанию dry-run. Используй --apply чтобы применить изменения.
    """
    from collections import defaultdict
    from datetime import timedelta

    _safe_setup_logging()

    from db.base import get_session
    from db.models import TrendCase

    GENERIC_MARKERS = {"мир", "world", "разное", "другое", "—", "null", "none", ""}

    def _is_generic(company: str | None) -> bool:
        return (company or "").strip().lower() in GENERIC_MARKERS

    since = datetime.utcnow() - timedelta(days=days)

    with get_session() as s:
        cases = (
            s.query(TrendCase)
            .filter(TrendCase.created_at >= since)
            .filter(TrendCase.is_duplicate == False)  # noqa: E712
            .filter(TrendCase.source_url.isnot(None))
            .all()
        )

        by_url: dict[str, list[TrendCase]] = defaultdict(list)
        for c in cases:
            by_url[c.source_url].append(c)

        suspicious_groups = {}
        for url, group in by_url.items():
            if len(group) < min_cases_per_url:
                continue
            generic_count = sum(1 for c in group if _is_generic(c.company))
            if generic_count / len(group) >= max_generic_ratio:
                suspicious_groups[url] = group

        if not suspicious_groups:
            typer.echo(
                f"Не найдено URL с признаками раздробленного обзора за последние {days} дней."
            )
            return

        typer.echo(f"Найдено {len(suspicious_groups)} URL с признаками дробления обзорного поста:\n")

        total_marked = 0
        for url, group in suspicious_groups.items():
            specific = [c for c in group if not _is_generic(c.company)]
            keep = specific[0] if specific else sorted(group, key=lambda c: c.created_at)[0]
            to_mark = [c for c in group if c.id != keep.id]

            generic_count = sum(1 for c in group if _is_generic(c.company))
            typer.echo(f"URL: {url}")
            typer.echo(
                f"  Кейсов: {len(group)}, без компании: {generic_count} "
                f"({int(generic_count / len(group) * 100)}%)"
            )
            typer.echo(
                f"  Оставляем: #{keep.id} ({keep.company or '—'}: {(keep.case_title or '')[:50]})"
            )
            for c in to_mark:
                typer.echo(
                    f"  → дубль: #{c.id} ({c.company or '—'}: {(c.case_title or '')[:50]})"
                )
                if not dry_run:
                    c.is_duplicate = True
                    c.duplicate_of_case_id = keep.id
            total_marked += len(to_mark)
            typer.echo()

        if dry_run:
            typer.echo(f"[DRY RUN] Было бы помечено дублями: {total_marked} кейсов.")
            typer.echo("Запусти с флагом --apply чтобы применить изменения.")
        else:
            typer.echo(f"✓ Помечено дублями: {total_marked} кейсов.")


@app.command()
def trends() -> None:
    """Показать все тренды в базе знаний с категориями."""
    _safe_setup_logging()
    from itertools import groupby
    from sqlalchemy import func

    from db.base import get_session
    from db.models import Trend, TrendCase

    with get_session() as s:
        rows = (
            s.query(
                Trend.id, Trend.name, Trend.category, Trend.status,
                func.count(TrendCase.id).label("cnt"),
            )
            .outerjoin(TrendCase, TrendCase.trend_id == Trend.id)
            .group_by(Trend.id)
            .order_by(Trend.category, Trend.name)
            .all()
        )
        data = [(r.id, r.name, r.category or "—", r.status or "active", r.cnt) for r in rows]

    if not data:
        typer.echo("Трендов нет. Запустите: python -m cli init-db")
        return

    SEP = "─" * 80
    typer.echo(f"\n{SEP}")
    typer.echo(f"  {'ID':<4} {'Тренд':<40} {'Статус':<10} {'Кейсов':>6}")
    typer.echo(SEP)
    for cat, group in groupby(sorted(data, key=lambda x: (x[2], x[1])), key=lambda x: x[2]):
        typer.echo(f"\n  📂 {cat}")
        for tid, name, _, status, cnt in group:
            typer.echo(f"  {tid:<4} {name[:40]:<40} {status:<10} {cnt:>6}")
    typer.echo(SEP)
    typer.echo(f"\n  Итого: {len(data)} трендов\n")


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


@app.command(name="llm-check")
def llm_check() -> None:
    """Проверить доступность LLM-провайдера и работу всех методов."""
    _safe_setup_logging()
    settings = get_settings()
    from llm.factory import create_llm_provider

    try:
        provider = create_llm_provider(settings)
    except Exception as e:
        typer.echo(f"✗ Ошибка инициализации: {e}")
        raise typer.Exit(code=1)

    if settings.llm_provider == "deepseek":
        typer.echo(f"Провайдер: deepseek (через artemox proxy)")
        typer.echo(f"Модель:    {settings.llm_model}")
        typer.echo(f"URL:       https://api.artemox.com/v1")
    elif settings.llm_provider == "yandex":
        typer.echo(f"Провайдер: {settings.llm_provider}")
        typer.echo(f"Folder ID: {settings.yandex_folder_id or '—'}")
        typer.echo(f"Модель:    gpt://{settings.yandex_folder_id}/{settings.yandex_model}")
    else:
        typer.echo(f"Провайдер: {settings.llm_provider}")
        typer.echo(f"Модель:    {settings.llm_model}")
        if settings.llm_base_url:
            typer.echo(f"URL:       {settings.llm_base_url}")
    if settings.groq_fallback_api_key:
        typer.echo(f"Fallback:  Groq {settings.groq_fallback_model}")

    typer.echo("\nПроверяю доступность...")
    if not provider.is_available():
        typer.echo("✗ Провайдер недоступен.")
        raise typer.Exit(code=1)
    typer.echo("✓ Провайдер доступен.\n")

    test_text = (
        "Сбербанк запустил Face Pay в 500 банкоматах. "
        "Технология позволяет снимать наличные по биометрии лица без карты. "
        "Конверсия использования банкоматов выросла на 23%."
    )

    try:
        typer.echo("1. Тест check_relevance...")
        relevant, reason = provider.check_relevance(test_text)
        typer.echo(f"   → relevant={relevant} | {reason}\n")

        typer.echo("2. Тест classify_post...")
        cls = provider.classify_post(test_text)
        typer.echo(f"   → type={cls['type']} | cases={cls['case_count']} | {cls['reason']}\n")

        typer.echo("3. Тест generate_summary...")
        summary = provider.generate_summary(test_text)
        typer.echo(f"   → {summary}\n")

        typer.echo("4. Тест extract_cases...")
        cases = provider.extract_cases(test_text, None)
        typer.echo(f"   → найдено кейсов: {len(cases)}")
        for c in cases[:2]:
            typer.echo(f"     • {c.get('case_title')} ({c.get('company')}, {c.get('industry')})")
        typer.echo("")

        typer.echo("5. Тест assign_trend...")
        from db.base import get_session
        from db.models import Trend
        with get_session() as s:
            trend_list = [
                {"id": t.id, "name": t.name, "description": t.description or "", "category": t.category or ""}
                for t in s.query(Trend).filter(Trend.status == "active").limit(22).all()
            ]
        if cases and trend_list:
            decision = provider.assign_trend(cases[0], trend_list)
            typer.echo(
                f"   → decision={decision['decision']} "
                f"| trend_id={decision['trend_id']} "
                f"| {decision['reasoning']}\n"
            )
        else:
            typer.echo("   → пропущено (нет кейсов или трендов в БД)\n")

        typer.echo("✓ Все методы работают.")
    except Exception as e:
        typer.echo(f"✗ Ошибка запроса: {e}")
        raise typer.Exit(code=1)


@app.command(name="llm-stats")
def llm_stats_cmd(
    hours: int = typer.Option(24, "--hours", "-h", help="За сколько часов"),
) -> None:
    """Статистика LLM-вызовов за период."""
    _safe_setup_logging()
    from datetime import timedelta
    from sqlalchemy import func
    from db.base import get_session
    from db.models import LLMCallLog

    since = datetime.utcnow() - timedelta(hours=hours)

    with get_session() as s:
        base_q = s.query(LLMCallLog).filter(LLMCallLog.called_at >= since)
        total_calls = base_q.count()
        if not total_calls:
            typer.echo(f"За последние {hours}ч LLM-вызовов не было.")
            return

        total_success = base_q.filter(LLMCallLog.success == True).count()  # noqa: E712
        total_failed = total_calls - total_success

        by_method = (
            s.query(
                LLMCallLog.method,
                func.count(LLMCallLog.id).label("calls"),
                func.sum(LLMCallLog.total_tokens).label("tokens"),
                func.avg(LLMCallLog.duration_ms).label("avg_ms"),
            )
            .filter(LLMCallLog.called_at >= since)
            .group_by(LLMCallLog.method)
            .order_by(func.sum(LLMCallLog.total_tokens).desc())
            .all()
        )

        total_tokens = (
            s.query(func.sum(LLMCallLog.total_tokens))
            .filter(LLMCallLog.called_at >= since)
            .scalar() or 0
        )
        total_cache_hit = (
            s.query(func.sum(LLMCallLog.cache_hit_tokens))
            .filter(LLMCallLog.called_at >= since)
            .scalar() or 0
        )
        total_cache_miss = (
            s.query(func.sum(LLMCallLog.cache_miss_tokens))
            .filter(LLMCallLog.called_at >= since)
            .scalar() or 0
        )

    typer.echo(f"\n{'═' * 78}")
    typer.echo(f"  LLM статистика за последние {hours}ч")
    typer.echo(f"{'═' * 78}")
    typer.echo(
        f"  Всего вызовов:   {total_calls} "
        f"(успешных: {total_success}, упало: {total_failed})"
    )
    if total_tokens:
        typer.echo(f"  Всего токенов:   {total_tokens:,}")
    else:
        typer.echo("  Всего токенов:   n/a")
    if total_cache_hit + total_cache_miss > 0:
        cache_pct = int(total_cache_hit / (total_cache_hit + total_cache_miss) * 100)
        typer.echo(
            f"  Cache hit:       {cache_pct}% "
            f"({total_cache_hit:,} / {total_cache_hit + total_cache_miss:,})"
        )

    typer.echo(f"\n{'Метод':<38} {'Вызовов':>8} {'Токенов':>12} {'Ср.мс':>7}")
    typer.echo(f"{'─' * 78}")
    for row in by_method:
        tokens_str = f"{int(row.tokens):,}" if row.tokens else "n/a"
        avg_ms = int(row.avg_ms or 0)
        typer.echo(f"  {row.method:<36} {row.calls:>8} {tokens_str:>12} {avg_ms:>7}")

    typer.echo(f"{'═' * 78}\n")


@app.command()
def bot() -> None:
    """Запустить Telegram-бота."""
    import asyncio
    from bot.main import main
    asyncio.run(main())
