# Telegram user-assistant (Telethon)

User-client (не BotFather-бот): отдельный Telegram-аккаунт через **Telethon** слушает указанные чаты/каналы, фильтрует сообщения по ключевым словам, при необходимости **пересылает оригинал** и/или отправляет **переработанный текст** из локальной LLM (**Ollama**) в целевые чаты.

## Требования

- Python **3.11+**
- Аккаунт Telegram + `API_ID` / `API_HASH` с [my.telegram.org](https://my.telegram.org)
- Для режима LLM: запущенный Ollama (по умолчанию `http://localhost:11434/api/generate`)

## Установка

```bash
cd telegram_user_assistant
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env` (минимум `API_ID`, `API_HASH`, `SOURCE_CHATS`, `TARGET_CHATS`, `FILTER_KEYWORDS`).

## Запуск

Из корня репозитория:

```bash
python -m app.main
```

При первом входе Telethon запросит код из Telegram/SMS.

Альтернатива:

```bash
python app/main.py
```

(в `app/main.py` добавлен путь к корню проекта, чтобы импорты `app.*` работали.)

## Как добавить канал-источник

В `.env` в массив `SOURCE_CHATS` добавьте `@username` без `@` или числовой id (часто для каналов: `-100...`):

```env
SOURCE_CHATS=["news_channel","-1001234567890"]
```

Перезапустите клиент.

## Как добавить канал-получатель

В `.env` расширьте `TARGET_CHATS` так же (username или id):

```env
TARGET_CHATS=["me","-1009876543210"]
```

## Как добавить фильтр (ключевые слова)

В `.env` в `FILTER_KEYWORDS` добавьте подстроки (совпадение **без учёта регистра**):

```env
FILTER_KEYWORDS=["срочно","release","CVE"]
```

Пустой список означает, что **ни одно** сообщение не пройдёт фильтр (в лог будет warning).

## Как поменять промпт для LLM

Отредактируйте `prompts/message_analyzer.txt` или задайте путь в `.env`:

```env
PROMPT_FILE=prompts/message_analyzer.txt
```

## Поведение флагов

- `FORWARD_ORIGINAL=true` — переслать исходное сообщение в каждый `TARGET_CHATS`.
- `USE_LLM=true` — отправить текст сообщения в Ollama и результат **текстом** в каждый `TARGET_CHATS`.
- Оба флага можно включить одновременно.

## Защита от повторной обработки

Используется SQLite (`DEDUP_DB_PATH`): пара `(chat_id, message_id)` сохраняется **после успешной** обработки (пересылка/LLM по включённым режимам). Если обработка упала с исключением, сообщение может быть обработано повторно при следующем событии.

## Структура

```
telegram_user_assistant/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── logger.py
│   ├── handlers/
│   │   └── new_message.py
│   └── services/
│       ├── forwarder.py
│       ├── filter_service.py
│       ├── llm_service.py
│       └── storage.py
├── prompts/
│   └── message_analyzer.txt
├── .env.example
├── requirements.txt
└── README.md
```

## Важно

- Убедитесь, что аккаунт **уже вступил** в источники/цели (каналы/группы), иначе Telethon не сможет читать/писать туда.
- Соблюдайте правила Telegram и законодательство; этот проект — инфраструктура, ответственность за использование на вас.
