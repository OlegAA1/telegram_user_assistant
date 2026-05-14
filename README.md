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

Заполните `.env` (минимум `API_ID`, `API_HASH`, `TARGET_CHATS` и источники: `SOURCE_CHATS` и/или `SOURCE_KEYWORD_RULES`, плюс ключевые слова — см. ниже).

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

Интерактивный запуск в терминале останавливается по **Ctrl+C**. Чтобы ассистент работал **постоянно** после выхода из SSH, используйте **systemd** (или временно `tmux` / `screen`).

## Запуск постоянно (systemd, Linux)

1. Убедитесь, что ручной запуск из каталога проекта работает (`python -m app.main`), затем остановите **Ctrl+C**.

2. Скопируйте пример unit-файла и отредактируйте пути и `User`:

   ```bash
   sudo cp deploy/telegram-assistant.service.example /etc/systemd/system/telegram-assistant.service
   sudo nano /etc/systemd/system/telegram-assistant.service
   ```

   Замените `YOUR_USER` и три пути `/home/YOUR_USER/telegram_user_assistant` на реальные (для клона в `/root/...` — соответственно `User=root` и `/root/telegram_user_assistant`).

3. Включите и запустите сервис:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-assistant.service
   sudo systemctl start telegram-assistant.service
   sudo systemctl status telegram-assistant.service
   ```

4. Логи:

   ```bash
   journalctl -u telegram-assistant.service -f
   ```

   **Ctrl+C** в этом просмотре только выходит из `journalctl`, сервис не останавливается.

5. После смены `.env` или обновления кода:

   ```bash
   sudo systemctl restart telegram-assistant.service
   ```

Файлы `.env` и `*.session` должны лежать в **корне проекта** (`WorkingDirectory`), как при ручном запуске.

## Команда `/ask` в личке (только владелец)

В `.env` укажите **`OWNER_ID`** — числовой Telegram **user id** владельца (тот, кто пишет ассистенту в личку). Узнать свой id: боты вроде `@userinfobot`, или если ассистент на **вашем** же аккаунте — смотрите `Logged in as id=...` в логах.

Поведение:

- Только **входящие** личные сообщения (`incoming`) от пользователя с этим `OWNER_ID`.
- Если текст начинается с **`/ask`**, всё, что после команды, уходит в **Ollama** (`LLM_API_URL`, модель **`LLM_MODEL`**), ответ отправляется **ответом в тот же чат**.
- Только **`/ask`** без текста → ответ: `Напиши вопрос после /ask`.
- Для **любых других** пользователей обработчик **ничего не отвечает** (команда игнорируется).
- Если **`OWNER_ID`** не задан — `/ask` **отключён**.

`USE_LLM` на автоматическую обработку каналов не влияет: для `/ask` достаточно рабочих `LLM_API_URL` и `LLM_MODEL`.

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

Пустой список означает, что **ни одно** сообщение не пройдёт фильтр по этой ветке (в лог будет warning).

## Разные ключевые слова для разных чатов

Опционально задайте **`SOURCE_KEYWORD_RULES`** — JSON-массив объектов с полями `source` и `keywords`. Для чата из правила проверяются **только** его слова (как минимум одно вхождение, без учёта регистра).

```env
SOURCE_KEYWORD_RULES=[
  {"source":"channel_a","keywords":["релиз","release"]},
  {"source":"-1001234567890","keywords":["CVE","уязвимость"]}
]
```

Подписка на новые сообщения идёт по **объединению** `SOURCE_CHATS` и всех `source` из правил (дубликаты убираются).

Поведение:

- Если для чата есть правило в `SOURCE_KEYWORD_RULES` — используются **только** его `keywords` (глобальный `FILTER_KEYWORDS` для этого чата не применяется).
- Если чат указан **только** в `SOURCE_CHATS` и под него **нет** правила — действует **`FILTER_KEYWORDS`** (общий список).
- Можно комбинировать: часть чатов с отдельными правилами, часть — под общий `FILTER_KEYWORDS`.

Если `SOURCE_KEYWORD_RULES` не задан, работает только глобальный **`FILTER_KEYWORDS`**, как раньше.

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
│   │   ├── new_message.py
│   │   └── owner_ask.py
│   └── services/
│       ├── forwarder.py
│       ├── filter_service.py
│       ├── llm_service.py
│       └── storage.py
├── deploy/
│   └── telegram-assistant.service.example
├── prompts/
│   └── message_analyzer.txt
├── .env.example
├── requirements.txt
└── README.md
```

## Важно

- Убедитесь, что аккаунт **уже вступил** в источники/цели (каналы/группы), иначе Telethon не сможет читать/писать туда.
- Соблюдайте правила Telegram и законодательство; этот проект — инфраструктура, ответственность за использование на вас.
