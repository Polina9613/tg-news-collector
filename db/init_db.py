from loguru import logger
from sqlalchemy import func, select, text

from db.base import Base, engine, get_session
from db.models import AuditLog, BotUser, NewsCard, RawPost, Source, Trend, TrendCase  # noqa: F401 — registers all models with Base


def migrate_add_url_fields() -> None:
    """Добавляет поля ссылок в существующую БД если их нет."""
    with engine.connect() as conn:
        existing_raw = [row[1] for row in conn.execute(text("PRAGMA table_info(raw_posts)"))]
        existing_news = [row[1] for row in conn.execute(text("PRAGMA table_info(news_cards)"))]
        if "extracted_urls" not in existing_raw:
            conn.execute(text("ALTER TABLE raw_posts ADD COLUMN extracted_urls TEXT"))
            conn.commit()
            logger.info("Migration: added extracted_urls to raw_posts")
        if "source_url" not in existing_news:
            conn.execute(text("ALTER TABLE news_cards ADD COLUMN source_url TEXT"))
            conn.commit()
            logger.info("Migration: added source_url to news_cards")


def migrate_add_llm_fields() -> None:
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(news_cards)"))]
        for col, definition in [
            ("summary", "TEXT"),
            ("llm_relevant", "BOOLEAN"),
            ("llm_enriched", "BOOLEAN DEFAULT 0"),
            ("llm_enriched_at", "DATETIME"),
        ]:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE news_cards ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to news_cards")
    Base.metadata.create_all(engine)
    logger.info("Migration: trend_cases table ready")


def migrate_add_trends() -> None:
    """Создаёт таблицу trends и добавляет поля в trend_cases."""
    Base.metadata.create_all(engine)  # создаст trends если нет
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(trend_cases)"))]
        for col, definition in [
            ("trend_id", "INTEGER REFERENCES trends(id)"),
            ("period_label", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE trend_cases ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to trend_cases")


def migrate_add_bot_tables() -> None:
    """Создаёт таблицы bot_users и audit_log если их нет."""
    Base.metadata.create_all(engine)
    logger.info("Migration: bot_users and audit_log tables ready")


def migrate_make_news_card_id_nullable() -> None:
    """Делает trend_cases.news_card_id nullable для поддержки кейсов, добавленных вручную.
    SQLite не умеет ALTER COLUMN — пересоздаём таблицу."""
    with engine.connect() as conn:
        info = conn.execute(text("PRAGMA table_info(trend_cases)")).all()
        col = next((r for r in info if r[1] == "news_card_id"), None)
        if col is None or col[3] == 0:
            # notnull == 0 → уже nullable, ничего не делаем
            return

        logger.info("Migration: making trend_cases.news_card_id nullable (recreating table)")
        conn.execute(text("""
            CREATE TABLE trend_cases_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_card_id INTEGER REFERENCES news_cards(id),
                trend_id INTEGER REFERENCES trends(id),
                trend_name TEXT,
                case_title TEXT,
                company TEXT,
                description TEXT,
                how_it_works TEXT,
                value TEXT,
                source_url TEXT,
                market TEXT,
                period_label TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("INSERT INTO trend_cases_v2 SELECT * FROM trend_cases"))
        conn.execute(text("DROP TABLE trend_cases"))
        conn.execute(text("ALTER TABLE trend_cases_v2 RENAME TO trend_cases"))
        conn.commit()
        logger.info("Migration: trend_cases.news_card_id is now nullable")


def migrate_remove_subscriptions() -> None:
    """Удаляет таблицу subscriptions и поле last_subs_digest_at, переводит subscriber → analyst."""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS subscriptions"))
        conn.commit()
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "bot_users" not in tables:
            return
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(bot_users)"))]
        if "last_subs_digest_at" not in existing:
            # Уже чистая БД или свежая установка
            conn.execute(text(
                "UPDATE bot_users SET role = 'analyst' WHERE role = 'subscriber'"
            ))
            conn.commit()
            return
        # Пересоздаём таблицу без last_subs_digest_at, заодно меняем роль
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                role TEXT DEFAULT 'analyst',
                is_active INTEGER DEFAULT 1,
                joined_at DATETIME,
                last_active_at DATETIME
            )
        """))
        conn.execute(text("""
            INSERT INTO bot_users_new
                (id, telegram_id, username, first_name, last_name,
                 role, is_active, joined_at, last_active_at)
            SELECT id, telegram_id, username, first_name, last_name,
                   CASE WHEN role = 'subscriber' THEN 'analyst' ELSE role END,
                   is_active, joined_at, last_active_at
            FROM bot_users
        """))
        conn.execute(text("DROP TABLE bot_users"))
        conn.execute(text("ALTER TABLE bot_users_new RENAME TO bot_users"))
        conn.commit()
        logger.info("Migration: removed subscriptions table, subscriber→analyst")


def migrate_add_retry_after() -> None:
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(news_cards)"))]
        if "llm_retry_after" not in existing:
            conn.execute(text(
                "ALTER TABLE news_cards ADD COLUMN llm_retry_after DATETIME"
            ))
            conn.commit()
            logger.info("Migration: added llm_retry_after to news_cards")


def migrate_add_source_topics() -> None:
    """Добавляет колонку topics в sources если её нет (для старых установок)."""
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(sources)"))]
        if "topics" not in existing:
            conn.execute(text("ALTER TABLE sources ADD COLUMN topics TEXT"))
            conn.commit()
            logger.info("Migration: added topics to sources")


def migrate_trends_v2() -> None:
    """Очищает таблицу trends, добавляет новые поля, заливает канонический список."""
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        # 1. Новые колонки в trends
        existing_trends_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(trends)"))]
        for col, definition in [
            ("status", "TEXT DEFAULT 'active'"),
            ("category", "TEXT"),
            ("proposed_by_case_id", "INTEGER"),
        ]:
            if col not in existing_trends_cols:
                conn.execute(text(f"ALTER TABLE trends ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to trends")

        # 2. Новые колонки в trend_cases
        existing_tc_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(trend_cases)"))]
        for col, definition in [
            ("industry", "TEXT"),
            ("is_duplicate", "BOOLEAN DEFAULT 0"),
            ("duplicate_of_case_id", "INTEGER"),
        ]:
            if col not in existing_tc_cols:
                conn.execute(text(f"ALTER TABLE trend_cases ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to trend_cases")

        # 3. Очистить мусорные тренды, открепить кейсы
        existing_trend_count = conn.execute(text("SELECT COUNT(*) FROM trends")).scalar()
        if existing_trend_count and existing_trend_count > 0:
            # Проверяем, уже ли залиты канонические тренды
            canonical_check = conn.execute(
                text("SELECT COUNT(*) FROM trends WHERE name = 'Биометрические платежи'")
            ).scalar()
            if not canonical_check:
                conn.execute(text("UPDATE trend_cases SET trend_id = NULL"))
                conn.execute(text("DELETE FROM trends"))
                conn.commit()
                logger.info("Migration: cleared all existing trends, cases unlinked")

    _seed_canonical_trends()


def _seed_canonical_trends() -> None:
    """Заливает 22 канонических тренда в БД."""
    import re

    from transliterate import translit

    from db.models import Trend

    CANONICAL_TRENDS = [
        # Платежи и денежные средства
        ("Биометрические платежи", "Платежи",
         "Оплата по лицу, ладони, голосу или другим биометрическим параметрам. "
         "Замена карт и смартфонов биометрической идентификацией для платёжных операций."),
        ("Платежи со смартфона", "Платежи",
         "Бесконтактные платежи через NFC, QR-коды, Tap-to-Pay, биометрия в мобильном "
         "приложении. Эволюция смартфона как универсального платёжного устройства."),
        ("Бесшовные платёжные сценарии", "Платежи",
         "One-click оплата, СБП, embedded payments, мгновенные переводы. "
         "Снижение трения в платёжном опыте, интеграция платежей в нефинансовые сервисы."),
        ("Физическая платёжная инфраструктура", "Платежи",
         "POS-терминалы, кассы самообслуживания, пользовательские платёжные устройства. "
         "Эволюция офлайн-инфраструктуры приёма платежей."),

        # Цифровые активы
        ("Цифровые валюты ЦБ", "Цифровые активы",
         "CBDC, цифровой рубль, программируемые деньги от центральных банков. "
         "Третья форма национальной валюты в дополнение к наличным и безналу."),
        ("Криптовалюты", "Цифровые активы",
         "Биткоин, эфир, обращение криптовалют. Регулирование, биржи, "
         "майнинг, инфраструктура для частных и институциональных инвесторов."),
        ("Стейблкоины и токенизация активов", "Цифровые активы",
         "Токенизированные депозиты, RWA (real-world assets), стейблкоины. "
         "Перенос традиционных активов на блокчейн-инфраструктуру."),

        # ИИ в финансах
        ("ИИ-агенты в банкинге", "ИИ",
         "Автономные LLM-ассистенты выполняющие банковские операции, "
         "обрабатывающие заявки, принимающие решения без участия оператора."),
        ("GenAI в клиентском сервисе", "ИИ",
         "Генеративный ИИ в чат-ботах, голосовых ассистентах, общении с клиентами. "
         "Замена скриптовых ботов на LLM-powered решения."),
        ("ИИ в кредитном скоринге", "ИИ",
         "Машинное обучение для оценки заёмщиков, риск-моделей, прогнозирования "
         "дефолтов. Замена традиционных статистических моделей на ML."),
        ("ИИ для Next Best Action", "ИИ",
         "ML-модели рекомендующие следующее действие или продукт для клиента. "
         "Персонализация продуктовых предложений и коммуникаций."),
        ("Альтернативные данные в финансах", "ИИ",
         "Нетрадиционные источники данных для скоринга и аналитики: транзакции, "
         "геолокация, поведение в приложениях, соцсети, телеком-данные."),

        # Инфраструктура и ПО
        ("Импортозамещение банковского ПО", "Инфраструктура",
         "Замена иностранного ПО на отечественные АБС, ERP, CRM, инфраструктурный софт. "
         "Переход на российский технологический стек."),
        ("Open API и Open Banking", "Инфраструктура",
         "Стандарты обмена данными между банками, финтехами и сторонними сервисами. "
         "API-экономика в финансах, регулирование доступа к данным."),
        ("Антифрод и кибербезопасность платежей", "Инфраструктура",
         "Защита от мошенничества, биометрический антифрод, поведенческий анализ, "
         "защита от социальной инженерии и кибератак на платёжную инфраструктуру."),

        # Регулирование и новые модели
        ("RegTech", "Регулирование",
         "Технологии для соответствия требованиям регуляторов: автоматизация AML/KYC, "
         "комплаенс, отчётность, мониторинг транзакций."),
        ("Embedded finance", "Регулирование",
         "Встраивание финансовых услуг в нефинансовые продукты: BNPL в e-commerce, "
         "страхование в каршеринге, кредиты в маркетплейсах."),
        ("ESG и устойчивые финансы", "Регулирование",
         "Зелёные облигации, ESG-скоринг, устойчивое инвестирование, "
         "учёт климатических рисков в финансовых продуктах."),

        # Пользовательский опыт
        ("Геймификация продуктов", "UX",
         "Игровые механики в финансовых и нефинансовых продуктах: достижения, "
         "квесты, рейтинги, виртуальные награды для удержания пользователей."),
        ("Метавселенные и Web3", "UX",
         "VR/AR в продуктах, NFT, виртуальные представительства брендов, "
         "интеграция Web3-технологий в потребительский опыт."),
        ("Голосовые интерфейсы", "UX",
         "Voice banking, голосовое управление финансами, интеграция с умными "
         "колонками и голосовыми ассистентами."),

        # Сегменты
        ("Финтех для МСБ", "Сегменты",
         "Продукты для малого и среднего бизнеса: расчётные сервисы, кредитование, "
         "экосистемные предложения, цифровизация бухгалтерии и налогов."),
    ]

    def _make_slug(name: str) -> str:
        try:
            latin = translit(name, "ru", reversed=True)
        except Exception:
            latin = name
        return re.sub(r"[^a-z0-9]+", "-", latin.lower().strip()).strip("-")[:80]

    seeded = 0
    with get_session() as session:
        for name, category, description in CANONICAL_TRENDS:
            if session.query(Trend).filter_by(name=name).first():
                continue
            session.add(Trend(
                name=name,
                slug=_make_slug(name),
                description=description,
                category=category,
                status="active",
            ))
            seeded += 1
    if seeded:
        logger.info(f"Migration: seeded {seeded} canonical trends")


def init_db() -> None:
    migrate_remove_subscriptions()
    Base.metadata.create_all(engine)
    logger.info("Database initialized: tables created (or already exist)")
    migrate_add_url_fields()
    migrate_add_llm_fields()
    migrate_add_trends()
    migrate_add_bot_tables()
    migrate_make_news_card_id_nullable()
    migrate_add_source_topics()
    migrate_trends_v2()
    migrate_add_retry_after()


def get_db_stats() -> dict:
    with get_session() as session:
        sources = session.scalar(select(func.count()).select_from(Source)) or 0
        raw_posts = session.scalar(select(func.count()).select_from(RawPost)) or 0
        news_cards = session.scalar(select(func.count()).select_from(NewsCard)) or 0
        trend_cases = session.scalar(select(func.count()).select_from(TrendCase)) or 0
        trends = session.scalar(select(func.count()).select_from(Trend)) or 0
        by_status_rows = session.execute(
            select(NewsCard.review_status, func.count()).group_by(NewsCard.review_status)
        ).all()
        by_status = {row[0]: row[1] for row in by_status_rows}
    return {
        "sources": sources,
        "raw_posts": raw_posts,
        "news_cards": news_cards,
        "trend_cases": trend_cases,
        "trends": trends,
        "by_status": by_status,
    }
