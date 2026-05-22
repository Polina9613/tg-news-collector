# Деплой на сервер

## Требования

- Python 3.11+
- Linux (Ubuntu 20.04+) или macOS
- 1 GB RAM минимум
- Доступ в интернет (Telegram API, Groq API)

## Установка

```bash
git clone <url>
cd tg-news-collector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp sources.example.yaml sources.yaml
# Заполнить .env реальными данными
python -m cli init-db
```

## Первая авторизация Telegram

Авторизацию нужно пройти один раз вручную (требует ввода SMS-кода):
```bash
python -m cli collect --days 1
# Введите код из Telegram
```
После этого сессия сохраняется в `tg_news.session`.

## Вариант 1 — screen

```bash
screen -S tg-news
python -m cli watch --interval 30
# Ctrl+A, D — отключиться (процесс продолжает работать)
screen -r tg-news  # вернуться
```

## Вариант 2 — cron

```bash
crontab -e
```
```
# Каждые 30 минут — сбор и обработка
*/30 * * * * cd /path/to/tg-news-collector && .venv/bin/python -m cli collect --days 0.1 >> logs/cron.log 2>&1 && .venv/bin/python -m cli process >> logs/cron.log 2>&1 && .venv/bin/python -m cli enrich --limit 5 --min-score 25 >> logs/cron.log 2>&1

# Каждую пятницу в 17:00 — дайджест
0 17 * * 5 cd /path/to/tg-news-collector && .venv/bin/python -m cli digest-weekly >> logs/cron.log 2>&1
```

## Вариант 3 — systemd (рекомендуется для продакшн)

Создать `/etc/systemd/system/tg-news.service`:
```ini
[Unit]
Description=TG News Collector
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/tg-news-collector
ExecStart=/path/to/tg-news-collector/.venv/bin/python -m cli watch --interval 30
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-news
sudo systemctl start tg-news
sudo systemctl status tg-news
# Логи:
journalctl -u tg-news -f
```

## Важно

- Файл `.env` и `*.session` не должны попасть в git
- Базу данных рекомендуется бэкапить раз в день:
  `cp data/tg_news.db data/backups/tg_news_$(date +%Y%m%d).db`
- При переезде на новый сервер скопируйте `.env`,
  `sources.yaml` и `tg_news.session`
