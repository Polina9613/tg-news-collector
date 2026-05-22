"""
Тестовый скрипт: загружает новости напрямую в БД и прогоняет через processor.
Использование: python scripts/test_pipeline.py
Не требует Telegram.
"""

# DB_PATH должен быть выставлен до любых project-импортов —
# db/base.py читает его на уровне модуля при первом импорте.
import os

TEST_DB = "data/test_pipeline.db"
os.environ["DB_PATH"] = TEST_DB

# После этой строки можно импортировать проектные модули.
import json  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from db.base import Base, engine, get_session  # noqa: E402
from db.models import NewsCard, RawPost, Source  # noqa: E402
from exporter.excel import export_to_excel  # noqa: E402
from processor.pipeline import process_raw_posts  # noqa: E402

# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

TEST_POSTS = [
    {
        "message_id": 1,
        "text": """Сбербанк запустил оплату по биометрии в 500 банкоматах

Сбербанк расширил сеть банкоматов с поддержкой оплаты по лицу до 500 устройств по всей России. Технология Face Pay позволяет снимать наличные и проводить платежи без карты и телефона — достаточно посмотреть в камеру.

По словам представителя банка, точность распознавания составляет 99.97%. В планах до конца года охватить все 15 000 банкоматов сети.""",
    },
    {
        "message_id": 2,
        "text": """ЦБ РФ повысил ключевую ставку до 21%

Банк России на заседании 25 октября принял решение повысить ключевую ставку на 200 базисных пунктов — до 21% годовых. Это рекордный уровень за всю историю современной России.

Регулятор объясняет решение необходимостью снизить инфляцию, которая по итогам сентября составила 8.6% в годовом выражении. Следующее заседание запланировано на декабрь.""",
    },
    {
        "message_id": 3,
        "text": """Яндекс представил новую версию YandexGPT 5

Яндекс анонсировал выход языковой модели YandexGPT 5 с улучшенными возможностями для работы с русскоязычными текстами. Модель показала прирост качества на 40% по сравнению с предыдущей версией на бенчмарках понимания текста.

Модель доступна через API Яндекс Облака для корпоративных клиентов. Среди новых возможностей — улучшенный RAG, поддержка контекста до 128к токенов и встроенные инструменты для работы с документами.""",
    },
    {
        "message_id": 4,
        "text": """🎉 СКИДКА 50% на курс по инвестициям!

Только сегодня — легендарный курс «Как стать миллионером за 3 месяца» со скидкой 50%!
Записывайтесь прямо сейчас, места ограничены.
Ссылка: course.example.com

#реклама ООО «Финансовые Мечты» ИНН 7701234567""",
    },
    {
        "message_id": 5,
        "text": """Wildberries внедряет биометрическую идентификацию для продавцов

Маркетплейс Wildberries запускает систему верификации продавцов через биометрию. С января 2025 года все новые продавцы будут проходить обязательную идентификацию по лицу при регистрации.

Мера направлена на борьбу с мошенническими аккаунтами — по данным компании, ущерб от них составил более 2 млрд рублей в 2023 году.""",
    },
    {
        "message_id": 6,
        "text": """ВТБ и Россельхозбанк запустили совместную платформу для МСБ

ВТБ и Россельхозбанк объявили о создании совместной цифровой платформы для малого и среднего бизнеса. Платформа объединит расчётно-кассовое обслуживание, кредитование и бухгалтерские сервисы в едином интерфейсе.

Пилот запускается в 10 регионах России. По оценкам банков, потенциальная аудитория — более 500 тысяч предпринимателей.""",
    },
    {
        "message_id": 7,
        "text": """Погода в Москве на выходные""",
    },
    {
        "message_id": 8,
        "text": """Группа Астра представила новую версию Astra Linux 1.8

Группа Астра выпустила обновлённую версию отечественной операционной системы Astra Linux 1.8 с улучшенной поддержкой российского оборудования и новыми инструментами безопасности.

Система сертифицирована ФСТЭК и МО РФ. В новой версии расширена поддержка процессоров Эльбрус и Байкал, добавлены средства защиты от современных киберугроз. Более 200 государственных организаций уже перешли на новую версию в рамках программы импортозамещения.""",
    },
    {
        "message_id": 9,
        "text": """Партнёрский материал

Альфа-Банк предлагает выгодные условия по ипотеке от 8.5% годовых для новых клиентов.
Подробности на сайте alfabank.ru

erid: 2VtzqwQZBQk""",
    },
    {
        "message_id": 10,
        "text": """Тинькофф запустил корпоративное обучение для сотрудников МСБ

Т-Банк (Тинькофф) открыл бесплатный образовательный портал для сотрудников компаний малого и среднего бизнеса. На платформе доступны курсы по финансовой грамотности, бухгалтерии, налогообложению и цифровым инструментам.

В первый месяц зарегистрировалось более 12 000 сотрудников из 3 500 компаний. Курсы разработаны совместно с ВШЭ и Сколково.""",
    },
]

# ---------------------------------------------------------------------------
# Вспомогательные функции вывода
# ---------------------------------------------------------------------------

_W = 56  # ширина рамки
_SEP_THICK = "═" * _W
_SEP_THIN = "─" * _W


def _banner(text: str) -> None:
    print(_SEP_THICK)
    print(f" {text}")
    print(_SEP_THICK)


def _json_list(value: str | None) -> str:
    if not value:
        return "—"
    try:
        items = json.loads(value)
        return ", ".join(str(x) for x in items) if items else "—"
    except (json.JSONDecodeError, TypeError):
        return value or "—"


def _print_card_dict(idx: int, cd: dict) -> None:
    title = cd["title"] or "—"
    print(f"\n[{idx}] {title}")
    print(f"    {'Источник:':<14} @{cd['ch_username']}")
    print(f"    {'Реклама:':<14} {'Да' if cd['is_ad'] else 'Нет'}")
    print(f"    {'Темы:':<14} {_json_list(cd['topics'])}")
    print(f"    {'Теги:':<14} {_json_list(cd['tags'])}")
    print(f"    {'Компании:':<14} {_json_list(cd['companies'])}")
    print(f"    {'Релевантность:':<14} {cd['relevance_score']} / {cd['relevance_label']}")
    print(f"    {'Статус:':<14} {cd['review_status']}")
    print(f"    {_SEP_THIN}")


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------


def setup_db() -> None:
    Base.metadata.create_all(engine)


def create_test_source() -> int:
    with get_session() as session:
        from sqlalchemy import select

        existing = session.execute(
            select(Source).where(Source.username == "test_feed")
        ).scalar_one_or_none()
        if existing:
            return existing.id
        source = Source(
            username="test_feed",
            title="Test Feed",
            topics='["тест"]',
            is_active=True,
        )
        session.add(source)
        session.flush()
        return source.id


def load_test_posts(source_id: int) -> int:
    now = datetime(2024, 10, 25, 12, 0, 0)
    loaded = 0
    with get_session() as session:
        for p in TEST_POSTS:
            post = RawPost(
                source_id=source_id,
                message_id=p["message_id"],
                channel_username="test_feed",
                post_url=f"https://t.me/test_feed/{p['message_id']}",
                raw_text=p["text"],
                published_at=now,
                has_media=False,
                is_forwarded=False,
            )
            session.add(post)
            loaded += 1
    return loaded


def _card_to_dict(card: NewsCard, ch_username: str) -> dict:
    return {
        "title": card.title,
        "ch_username": ch_username,
        "is_ad": card.is_ad,
        "topics": card.topics,
        "tags": card.tags,
        "companies": card.companies,
        "relevance_score": card.relevance_score,
        "relevance_label": card.relevance_label,
        "review_status": card.review_status,
    }


def print_report(channel_username: str) -> dict:
    from sqlalchemy import select

    with get_session() as session:
        rows = session.execute(
            select(NewsCard, RawPost.channel_username)
            .join(RawPost, NewsCard.raw_post_id == RawPost.id)
            .order_by(NewsCard.id)
        ).all()
        card_dicts = [_card_to_dict(card, ch) for card, ch in rows]

    counts: dict = {
        "total_posts": len(TEST_POSTS),
        "cards": len(card_dicts),
        "ads": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "irrelevant": 0,
        "needs_review": 0,
        "auto": 0,
    }

    _banner(f"ТЕСТ PIPELINE — {len(TEST_POSTS)} постов")

    for idx, cd in enumerate(card_dicts, 1):
        _print_card_dict(idx, cd)
        if cd["is_ad"]:
            counts["ads"] += 1
        label = cd["relevance_label"]
        counts[label] = counts.get(label, 0) + 1
        if cd["review_status"] == "needs_review":
            counts["needs_review"] += 1
        else:
            counts["auto"] += 1

    return counts


def print_summary(counts: dict, excel_path: str) -> None:
    print()
    _banner("СВОДКА")
    w = 22
    print(f" {'Всего постов:':<{w}}{counts['total_posts']}")
    print(f" {'Создано карточек:':<{w}}{counts['cards']}")
    print(f" {'Рекламных:':<{w}}{counts['ads']}")
    print(f" {'High релевантность:':<{w}}{counts.get('high', 0)}")
    print(f" {'Medium:':<{w}}{counts.get('medium', 0)}")
    print(f" {'Low:':<{w}}{counts.get('low', 0)}")
    print(f" {'Irrelevant:':<{w}}{counts.get('irrelevant', 0)}")
    print(f" {'needs_review:':<{w}}{counts['needs_review']}")
    print(f" {'auto:':<{w}}{counts['auto']}")
    print()
    print(f" Excel: {excel_path}")
    print(_SEP_THICK)


def ask_cleanup() -> None:
    try:
        answer = input("\nУдалить тестовую БД? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer == "y":
        Path(TEST_DB).unlink(missing_ok=True)
        print(f"✓ Удалено: {TEST_DB}")
    else:
        print(f"  БД сохранена: {TEST_DB}")


def main() -> None:
    print(f"\n  Тестовая БД: {TEST_DB}\n")

    setup_db()
    source_id = create_test_source()
    n = load_test_posts(source_id)
    print(f"  Загружено постов: {n}")

    print("  Запуск processor...")
    proc = process_raw_posts()
    print(f"  Создано карточек: {proc.created}  |  Пропущено (пустые): {proc.skipped_empty}")

    counts = print_report("test_feed")

    ts = datetime.now().strftime("%Y%m%d")
    excel_path = f"data/exports/test_pipeline_{ts}.xlsx"
    Path(excel_path).parent.mkdir(parents=True, exist_ok=True)
    export_to_excel(output_path=excel_path)

    print_summary(counts, excel_path)
    ask_cleanup()


if __name__ == "__main__":
    main()
