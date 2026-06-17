# tg-news-collector

Автоматическая система мониторинга Telegram-каналов и формирования
финтех-дайджеста с базой знаний трендов. Работает 24/7 без участия команды.

## Возможности

- 🤖 **Telegram-бот** с двумя ролями: аналитик и администратор
- 📡 **Автоматический сбор** из Telegram-каналов каждые 30 минут
- 🧠 **Двухуровневая обработка**: rule-based + LLM (Groq или Ollama)
- 📊 **База знаний трендов** с поиском по компании, теме, периоду
- 📰 **Еженедельный Word-дайджест** для аналитиков по пятницам
- ✏️ **Редактор кейсов** прямо в Telegram (FSM)
- 📁 **Excel-экспорт** с цветовой кодировкой
- 🔧 **Управление каналами** через бота без правки YAML
- 📈 **85+ автотестов**, готов к продакшну

## Архитектура

```
Telegram-каналы
    ↓
[Collector] Telethon — сбор постов в raw_posts
    ↓
[Processor] rule-based: очистка, темы, теги, релевантность
    ↓                              → NewsCard
[LLM Enricher] Groq/Ollama: структурирование в кейсы
    ↓                              → TrendCase + Trend
[Digest Generator] LLM компонует .docx
    ↓
[Telegram Bot] рассылка + поиск + редактирование
```

## Стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.11+ |
| Telegram (сбор) | Telethon |
| Telegram (бот) | aiogram 3.x |
| Планировщик | APScheduler |
| База данных | SQLite + SQLAlchemy 2.0 |
| Настройки | Pydantic Settings |
| LLM | Groq API или Ollama |
| Excel | pandas + openpyxl |
| Word | python-docx |
| CLI | typer |
| Логи | loguru |
| Тесты | pytest (85+ тестов) |

## Быстрый старт

### 1. Установить

```bash
git clone https://github.com/Polina9613/tg-news-collector.git
cd tg-news-collector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Получить ключи

**Telegram API** — на https://my.telegram.org → API development tools → Create application

**LLM на выбор:**
- **Groq** (облако, бесплатно) — на https://console.groq.com → API Keys
- **Ollama** (свой сервер) — `ollama pull qwen2.5:14b` на сервере с GPU

**Telegram-бот** — у @BotFather → `/newbot`

### 3. Настроить

```bash
cp .env.example .env
cp sources.example.yaml sources.yaml
```

Заполнить `.env`:
```env
# Telegram сбор
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=xxx
TELEGRAM_PHONE=+79001234567

# Telegram бот
BOT_TOKEN=ваш_токен_от_botfather
BOT_ADMIN_SECRET=любое_длинное_кодовое_слово

# LLM (один из двух вариантов)
LLM_PROVIDER=groq
LLM_API_KEY=gsk_xxx
LLM_MODEL=llama-3.3-70b-versatile

# ИЛИ для Ollama
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://your-server:11434
# LLM_MODEL=qwen2.5:14b
```

### 4. Запустить

```bash
# Создать базу
python -m cli init-db

# Первая авторизация в Telegram (ввод SMS-кода)
python -m cli collect --days 1

# Проверить что LLM работает
python -m cli llm-check

# Запустить бота — он сам будет всё делать дальше
python -m cli bot
```

В Telegram открыть своего бота → `/start` → `/admin ваше_кодовое_слово`

## Роли пользователей

| Роль | Как получить | Что доступно |
|---|---|---|
| Аналитик | Автоматически при `/start` | Поиск, тренды, Excel, дайджест |
| Администратор | `/admin <кодовое_слово>` или `/promote @user` | Всё + редактор кейсов, каналы, пользователи |

## Что делает бот автоматически

| Время | Что происходит |
|---|---|
| Каждые 30 минут | Собирает новые посты → обрабатывает → обогащает LLM |
| Пятница 16:00 | Отправляет админам Excel за неделю на финальную проверку |
| Пятница 18:00 | Генерирует и рассылает дайджест всем пользователям |

## Команды бота

### Для аналитика
- `/start /menu /help`
- `/search <текст>` — поиск по подстроке в кейсах
- `/company <название>` — кейсы по компании
- `/topic <тема> [дней]` — кейсы по теме за период
- `/trends /trend <id> /search_trend <id>` — работа с трендами
- `/export 7|30|all` — Excel-выгрузка
- `/digest_now` — последний дайджест
- `/stats` — статистика
- `/excel_guide /user_guide` — описание Excel и руководство

### Для админа (дополнительно)
- `/review /add` — редактор кейсов с FSM
- `/channels /add_channel /toggle_channel /remove_channel`
- `/users /promote /demote /admin`
- `/collect /process /enrich` — ручной запуск парсера
- `/digest` — сгенерировать дайджест вручную
- `/broadcast_digest` — ручная рассылка

Подробное руководство для пользователей: `docs/user_guide.docx`

## CLI-команды

В продакшене запускается только `python -m cli bot` — бот сам делает остальное. CLI нужно для разработки, тестов и форс-мажоров.

| Команда | Описание |
|---|---|
| `python -m cli bot` | Запустить Telegram-бота (продакшн) |
| `python -m cli init-db` | Создать/обновить БД и применить миграции |
| `python -m cli collect --days 7` | Собрать посты вручную |
| `python -m cli process` | Обработать сырые посты |
| `python -m cli enrich-all --batch-size 5 --pause 180` | LLM-обогащение всех |
| `python -m cli digest --days 7` | Сгенерировать дайджест |
| `python -m cli export` | Экспорт в Excel |
| `python -m cli stats` | Статистика базы |
| `python -m cli trends` | Список трендов |
| `python -m cli search --query "биометрия"` | Поиск кейсов |
| `python -m cli llm-check` | Проверить LLM-провайдер |

## Структура проекта

```
tg-news-collector/
├── config/             # Настройки (Pydantic)
├── db/                 # Модели SQLAlchemy + миграции
├── collector/          # Сбор из Telegram (Telethon)
├── processor/          # Rule-based обработка
├── llm/                # Groq и Ollama провайдеры
├── digest/             # Генератор Word-дайджеста
├── exporter/           # Excel-экспорт
├── bot/                # Telegram-бот (aiogram)
│   ├── handlers/       # 8 роутеров
│   ├── scheduler.py    # Auto pipeline + рассылки
│   ├── menu.py         # Меню по ролям
│   └── ...
├── cli/                # CLI-команды (typer)
├── tests/              # 85+ тестов
├── scripts/            # Утилиты
├── docs/
│   ├── server_setup.md # Деплой на сервер
│   ├── user_guide.docx # Руководство пользователя
│   └── excel_guide.md
└── data/               # БД, экспорты, дайджесты (gitignored)
```

## Модели данных

```
Source         — Telegram-каналы из sources.yaml
RawPost        — Сырые посты как есть
NewsCard       — Обработанная карточка
TrendCase      — Структурированный кейс от LLM
Trend          — Тренд как сущность базы знаний
BotUser        — Пользователи бота (analyst / admin)
AuditLog       — Лог всех действий
```

## Поиск

| Команда | Где ищет | Тип сравнения |
|---|---|---|
| `/search` | name + description + value + how_it_works + company + trend_name | Подстрока, регистронезависимо |
| `/company` | поле company | Подстрока, регистронезависимо |
| `/topic` | темы поста + теги + название тренда | Подстрока, регистронезависимо |

`/search цифр` найдёт «цифровой рубль», «цифровизация», «оцифровка». `/company сбер` найдёт «Сбербанк».

## LLM-провайдеры

Переключение одной строкой в `.env`:

### Groq (по умолчанию)
```env
LLM_PROVIDER=groq
LLM_API_KEY=gsk_xxx
LLM_MODEL=llama-3.3-70b-versatile
```
Бесплатно, 30 запросов/мин.

### Ollama (свой сервер)
```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://your-server:11434
LLM_MODEL=qwen2.5:14b
```
Без лимитов, данные не уходят наружу.

Подробнее в `docs/server_setup.md`.

## Деплой на сервер

См. `docs/server_setup.md` — три варианта: screen, cron, systemd.

Рекомендуемый — systemd, который автоматически перезапускает бота при падении.

Минимум команд:
```bash
git clone <repo>
cd tg-news-collector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
# Положить .env и sources.yaml
python -m cli init-db
python -m cli collect --days 1  # авторизация Telegram
# Настроить systemd из docs/server_setup.md
sudo systemctl enable --now tg-news
```

## Тесты

```bash
pytest tests/ -v
```

85+ тестов, работают без Telegram и LLM.

## Документация

| Файл | Для кого |
|---|---|
| `README.md` | Разработчики и девопсы |
| `docs/user_guide.docx` | Пользователи бота — аналитики |
| `docs/server_setup.md` | Деплой |
| `docs/excel_guide.md` | Описание Excel |

## Roadmap

- [ ] Streamlit веб-интерфейс для редактора
- [ ] RSS и веб-источники (не только Telegram)
- [ ] Квартальные отчёты по динамике трендов
- [ ] Полнотекстовый поиск (SQLite FTS5)
- [ ] PostgreSQL для больших объёмов