# tg-news-collector

Автоматическая система мониторинга Telegram-каналов для формирования
корпоративного финтех-дайджеста. Собирает посты, классифицирует их
по темам, структурирует в кейсы через LLM и генерирует еженедельный
Word-дайджест для аналитиков.

## Что умеет система

- Собирает посты из публичных Telegram-каналов через Telethon
- Очищает текст: убирает HTML, markdown, emoji
- Определяет рекламные посты автоматически
- Классифицирует по 18 темам и 60+ тегам через rule-based алгоритм
- Извлекает упомянутые компании
- Оценивает релевантность (score 0–100)
- Через LLM (Groq): проверяет релевантность, пишет резюме,
  структурирует кейсы в базу знаний трендов
- Генерирует еженедельный Word-дайджест
- Экспортирует всё в Excel для ручной проверки редактором
- Дедуплицирует посты по channel + message_id

## Стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.11+ |
| Telegram | Telethon |
| База данных | SQLite + SQLAlchemy 2.0 |
| Настройки | Pydantic Settings |
| LLM | Groq API (llama-3.3-70b-versatile) |
| Экспорт Excel | pandas + openpyxl |
| Экспорт Word | python-docx |
| CLI | typer |
| Логи | loguru |
| Тесты | pytest (72 теста) |

## Быстрый старт

### 1. Клонировать и установить

```bash
git clone <url>
cd tg-news-collector
python3 -m venv .venv
source .venv/bin/activate      # Linux/Mac
# .venv\Scripts\activate       # Windows
pip install -e .
```

### 2. Получить Telegram API credentials

1. Открыть https://my.telegram.org
2. Войти под своим номером телефона
3. Перейти в **API development tools**
4. Создать приложение (App title: любое, Platform: Other)
5. Скопировать `App api_id` и `App api_hash`

### 3. Получить Groq API key

1. Зарегистрироваться на https://console.groq.com
2. Перейти в **API Keys** → **Create API Key**
3. Скопировать ключ (начинается с `gsk_`)

Бесплатный тариф: 30 запросов/минуту, достаточно для работы.

### 4. Настроить конфигурацию

```bash
cp .env.example .env
cp sources.example.yaml sources.yaml
```

Заполнить `.env`:
```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE=+79001234567
TELEGRAM_SESSION_NAME=tg_news
DB_PATH=data/tg_news.db
SOURCES_FILE=sources.yaml
LOG_LEVEL=INFO
DEFAULT_COLLECT_DAYS=7
MIN_RELEVANCE_SCORE=25
LLM_ENABLED=true
LLM_PROVIDER=groq
LLM_API_KEY=gsk_ваш_ключ
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT=60
LLM_MIN_SCORE=25
```

Заполнить `sources.yaml` — список Telegram-каналов для мониторинга:
```yaml
channels:
  - username: "@fintechassociation"
    title: "Ассоциация ФинТех"
    topics: ["финтех", "банки", "платежи", "регуляторика"]
    active: true

  - username: "@blockchainRF"
    title: "Блокчейн / Web3 в России"
    topics: ["крипто / блокчейн", "регуляторика", "финтех"]
    active: true
```

### 5. Инициализировать базу и запустить

```bash
python -m cli init-db
python -m cli collect --days 7
python -m cli process
python -m cli enrich-all --min-score 25 --batch-size 5 --pause 180
python -m cli digest --days 7
python -m cli export
```

После первого запуска `collect` Telegram попросит ввести код из SMS.
После ввода создаётся файл `tg_news.session` — он сохраняет авторизацию.
Повторный ввод кода не потребуется.

## Структура проекта

```
tg-news-collector/
├── config/
│   └── settings.py          # Настройки через Pydantic (читает .env)
├── db/
│   ├── models.py             # Модели: Source, RawPost, NewsCard,
│   │                         #         TrendCase, Trend
│   ├── base.py               # SQLAlchemy engine, get_session()
│   └── init_db.py            # init_db(), get_db_stats(), миграции
├── collector/
│   ├── telegram.py           # TelegramCollector (Telethon)
│   └── sources_loader.py     # Загрузка sources.yaml
├── processor/
│   ├── cleaner.py            # clean_text(), extract_title()
│   ├── ads.py                # detect_ad()
│   ├── tagger.py             # assign_topics(), assign_tags(),
│   │                         # extract_companies()
│   ├── relevance.py          # compute_relevance() → score 0-100
│   ├── card_builder.py       # build_news_card()
│   ├── dedup.py              # is_duplicate()
│   └── pipeline.py           # process_raw_posts(), reprocess_all_cards()
├── llm/
│   ├── groq_provider.py      # Groq API клиент
│   ├── enricher.py           # enrich_news_cards() — LLM-обогащение
│   ├── trend_matcher.py      # get_or_create_trend() — база знаний
│   └── base.py               # BaseLLMProvider (ABC)
├── digest/
│   ├── generator.py          # generate_digest() → .docx
│   └── llm_digest.py         # Промпты: top5, facts, topic_intro
├── exporter/
│   └── excel.py              # export_to_excel() → .xlsx
├── cli/
│   └── main.py               # Все CLI-команды (typer)
├── tests/                    # 72 теста pytest
├── scripts/
│   └── test_pipeline.py      # Тест на синтетических данных
├── docs/
│   ├── excel_guide.md        # Как читать Excel-экспорт
│   └── server_setup.md       # Деплой на сервер
├── data/                     # Gitignored
│   ├── tg_news.db            # База данных SQLite
│   ├── exports/              # Excel-файлы
│   └── digests/              # Word-дайджесты
├── .env.example              # Шаблон переменных окружения
├── sources.example.yaml      # Пример списка каналов
└── pyproject.toml            # Зависимости и настройки инструментов
```

## Модели данных

```
Source          — Telegram-каналы из sources.yaml
RawPost         — Сырые посты как есть из Telegram
NewsCard        — Обработанная карточка новости
TrendCase       — Структурированный кейс от LLM
Trend           — Тренд как сущность базы знаний
```

Связи:
```
Source → (1:N) → RawPost → (1:1) → NewsCard → (1:N) → TrendCase → (N:1) → Trend
```

## CLI-команды

### Основные

| Команда | Описание |
|---|---|
| `python -m cli init-db` | Создать/обновить базу данных |
| `python -m cli collect --days 7` | Собрать посты за N дней |
| `python -m cli collect --channel @name` | Один канал |
| `python -m cli process` | Обработать посты → карточки |
| `python -m cli reprocess` | Пересчитать все карточки |
| `python -m cli enrich --limit 10` | LLM-обогащение N карточек |
| `python -m cli enrich-all --batch-size 5 --pause 180` | Обогатить все |
| `python -m cli digest --days 7` | Сгенерировать Word-дайджест |
| `python -m cli export` | Экспорт в Excel |
| `python -m cli stats` | Статистика базы |

### База знаний трендов

| Команда | Описание |
|---|---|
| `python -m cli trends` | Список всех трендов |
| `python -m cli trend-info --id 1` | Детали тренда |
| `python -m cli search --query "биометрия"` | Поиск по тексту |
| `python -m cli search --company "Сбер"` | Поиск по компании |
| `python -m cli search --period 2026-Q2` | Поиск по периоду |

### Автоматизация

| Команда | Описание |
|---|---|
| `python -m cli run-daily` | collect + process + export за 1 день |
| `python -m cli watch --interval 30` | Непрерывный режим (для сервера) |
| `python -m cli digest-weekly` | Еженедельный дайджест по расписанию |

## Как работает пайплайн

```
Telegram-канал
    ↓
[Collector] Telethon забирает посты, сохраняет в raw_posts
    ↓
[Processor]
    clean_text()       — убирает HTML, markdown, emoji
    detect_ad()        — маркеры рекламы (#реклама, erid, ООО)
    extract_title()    — первая содержательная строка
    assign_topics()    — 18 тем по словарям ключевых слов
    assign_tags()      — 60+ тегов
    extract_companies()— список компаний из текста
    compute_relevance()— score 0-100, label high/medium/low/irrelevant
    → NewsCard в БД
    ↓
[LLM Enricher] — только для карточек с score >= 25
    check_relevance()  — LLM подтверждает релевантность
    generate_summary() — резюме 2-3 предложения для сайта
    extract_cases()    — структурированные кейсы
    get_or_create_trend() — привязка к тренду в базе знаний
    → TrendCase + Trend в БД
    ↓
[Digest Generator] — раз в неделю
    get_top5()         — топ-5 новостей через LLM
    get_facts()        — числовые факты через LLM
    get_topic_intro()  — вводный абзац к каждой теме
    → .docx файл
    ↓
[Exporter]
    → .xlsx файл (листы: news_cards, review, trend_cases, trends, raw_posts)
```

## Цветовая кодировка Excel

| Цвет | Значение |
|---|---|
| Жёлтый | Рекламный пост — требует проверки перед публикацией |
| Зелёный | Высокая релевантность (score >= 60) |
| Серый | Низкая релевантность |

## Статусы карточек

| Статус | Значение |
|---|---|
| `auto` | Обработано автоматически |
| `needs_review` | Требует ручной проверки (реклама или score < 10) |
| `approved` | Одобрено редактором |
| `rejected` | Отклонено редактором |

## Деплой на сервер

Подробная инструкция в `docs/server_setup.md`.

Краткий вариант через cron:
```bash
# Каждые 30 минут — сбор новых постов
*/30 * * * * cd /path/to/project && .venv/bin/python -m cli collect --days 0.1 && .venv/bin/python -m cli process && .venv/bin/python -m cli enrich --limit 5 --min-score 25

# Каждую пятницу в 17:00 — еженедельный дайджест
0 17 * * 5 cd /path/to/project && .venv/bin/python -m cli digest-weekly
```

## Тесты

```bash
pytest tests/ -v        # запустить все тесты
pytest tests/ -v -k cleaner   # только тесты cleaner
```

Тесты работают без Telegram и без заполненного .env.
Покрытие: cleaner, ads, tagger, relevance, dedup, card_builder, exporter.

## Известные ограничения

- Только публичные Telegram-каналы
- Groq бесплатный тариф: 30 запросов/мин → при большом объёме
  используйте `--batch-size 5 --pause 180`
- При первом запуске требуется ввод кода из Telegram
- Файл `.session` нельзя коммитить в git (уже в .gitignore)

## Roadmap

- [ ] Streamlit веб-интерфейс для редактора
- [ ] RSS и веб-источники
- [ ] Telegram-бот для рассылки дайджеста
- [ ] Квартальные отчёты по трендам
- [ ] Полнотекстовый поиск (SQLite FTS5)
- [ ] Поддержка GigaChat / YandexGPT
