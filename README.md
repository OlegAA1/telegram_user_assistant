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

## Команда `/ask` в личке (разрешённые отправители)

В `.env` задайте **`ASK_SENDER_IDS`** — JSON-массив **числовых user id** Telegram-аккаунтов, с которых разрешено писать `/ask` ассистенту в **личку** (например, ваш второй аккаунт). Узнать id: `@userinfobot` и т.п.

Пример:

```env
ASK_SENDER_IDS=[123456789,987654321]
```

Поведение:

- Только **входящие** личные сообщения от user id из этого списка.
- Сообщение **`?`** — краткая памятка по доступным командам (удобно закрепить в чате).
- Команда **`/ask текст`** — текст уходит в Ollama (`LLM_API_URL`, `LLM_MODEL`), ответ приходит в тот же чат.
- **Обычный текст без `/`** (например «напомни мне в 23:30 открыть сайт») — сначала **intent** через локальную Qwen и `prompts/intent_parser.txt` (JSON): напоминание в **`ReminderStore`**, вопрос в LLM, web/current intent, deep analysis или ответ «не понял»; при невалидном JSON — fallback как у **`/ask`**.
- Только **`/ask`** без текста → `Напиши вопрос после /ask`.
- Остальные пользователи **не получают** ответов.
- Если **`ASK_SENDER_IDS`** пуст и не задан устаревший **`OWNER_ID`** — личные **`/ask`**, **`/remind`** и режим **ассистента без `/`** **выключены**.

Для обратной совместимости можно по-прежнему указать один id в **`OWNER_ID`** — он будет добавлен к списку разрешённых (удобно мигрировать со старого конфига).

`USE_LLM` на `/ask` не влияет: нужны только рабочие `LLM_API_URL` и `LLM_MODEL`.

### Если `/ask` не отвечает

1. В логах при старте должно быть **`/ask, /remind и личный ассистент (без /) для user ids: [...]`**. Если видно **`ASK_SENDER_IDS ... отключены`** — в `.env` пустой список и не задан **`OWNER_ID`**.
2. В **`ASK_SENDER_IDS`** должен быть numeric user id именно того аккаунта, с которого ты пишешь.
3. Писать нужно **в личку аккаунта ассистента** (того, под кем запущен Telethon), не в канал и не «Избранное» с другой логики, если она не совпадает с этим диалогом.
4. Команда в начале сообщения: **`/ask привет`** (латинские символы `/ask`).
5. Смотри логи после отправки: должна появиться строка **`/ask from sender_id=...`**. Если её нет — событие не доходит (не тот id / не личка / не тот аккаунт-получатель).
6. Проверь **`curl`** к Ollama с VPS (как в README про LLM) — при недоступной LLM будет ответ об ошибке или «пустой ответ».

## Local Qwen Mode

По умолчанию ассистент использует **локальную Qwen через Ollama** (`LLM_API_URL`, `LLM_MODEL`). Это основной режим для `/ask`, coding-задач, routing/intent parser и напоминаний.

## OpenRouter Fallback

OpenRouter подключается отдельно и используется только когда это явно нужно:

- `/cloud вопрос` — отправить вопрос во внешнюю модель.
- `/analyze текст` — глубокий анализ через OpenRouter.
- intent `web_search`, `cloud_ask`, `deep_analysis` от обычного сообщения.
- fallback, если локальная Qwen не ответила и **`ENABLE_CLOUD_FALLBACK=true`**.

Настройки:

```env
ENABLE_CLOUD_FALLBACK=false
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_TIMEOUT=60
```

Команда **`/provider`** показывает текущие модели и режимы.

## Web Search Mode

Команда:

```text
/search новости Ethereum сегодня
```

Провайдер **Tavily** (`app/services/web_search_service.py`). Результаты (`title`, `url`, `snippet`) сводятся через OpenRouter.

```env
ENABLE_WEB_SEARCH=true
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=tvly-...
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT=30
```

Если `ENABLE_WEB_SEARCH=false`, `/search` ответит, что режим отключён. При включённом поиске, но пустом ответе Tavily, бот попробует ответить через `/cloud` (нужен OpenRouter).

## Privacy Notes

- `OPENROUTER_API_KEY` хранится только в `.env`, не логируется и не должен попадать в Git.
- Приватные Telegram-сообщения по умолчанию обрабатываются локально.
- Cloud используется только по явным командам **`/cloud`**, **`/analyze`**, intent `web_search`/`cloud_ask`/`deep_analysis`, или при **`ENABLE_CLOUD_FALLBACK=true`** после пустого ответа local Qwen.
- Не отправляйте в OpenRouter приватные данные, если не хотите отдавать их внешнему провайдеру.

## Примеры команд

```text
?
/ask как сделать docker compose?
/cloud объясни сложную ошибку
/search новости Ethereum сегодня
/analyze <текст>
/provider
/dialogs
/dialogs channels
```

## Диалоги `/dialogs`

Команда **`/dialogs`** доступна только отправителям из `ASK_SENDER_IDS` / `OWNER_ID` и выводит список диалогов аккаунта Telethon:

```text
Название: Crypto News
Тип: channel
ID: -1001234567890
Username: @crypto_news
```

Фильтры:

```text
/dialogs
/dialogs channels
/dialogs groups
/dialogs users
```

ID из ответа удобно копировать в `SOURCE_CHATS`, `TARGET_CHATS`, правила мониторинга и будущие SQLite-настройки. Если диалогов много, ответ автоматически разбивается на несколько сообщений.

## Как обновлять `.env` без потери старых значений

После `git pull` новые переменные появляются в **`.env.example`**, а ваш рабочий **`.env`** Git не трогает. Не заменяйте `.env` целиком, чтобы не потерять `API_HASH`, `SESSION_NAME`, чаты и ключи.

Безопасный способ посмотреть, какие строки появились:

```bash
cd ~/telegram_user_assistant
diff -u .env .env.example
```

Дальше вручную добавьте недостающие строки:

```bash
nano .env
```

Например, если появились лимиты OpenRouter:

```env
MAX_CLOUD_REQUESTS_PER_DAY=30
MAX_CLOUD_INPUT_CHARS=12000
MAX_CLOUD_OUTPUT_TOKENS=1000
LOG_CLOUD_USAGE=true
```

После изменения `.env` перезапустите сервис:

```bash
sudo systemctl restart telegram-assistant.service
```

## Напоминания `/remind` (личка, те же `ASK_SENDER_IDS`)

Тем же списком разрешённых отправителей, что и для `/ask`, в личку ассистенту можно ставить напоминания. Время **абсолютных** напоминаний задаётся в часовом поясе **`REMINDER_TZ`**. По умолчанию в коде используется **`Europe/Moscow`** (МСК), поэтому `00:10` означает **00:10 по Москве**, если в `.env` не указано другое.

Примеры:

```text
/remind 2026-05-21 18:30 Вынуть стирку
/remind in 45m Позвонить
/remind in 2h Проверить почту
/remind list
/remind cancel 3
```

- База напоминаний: **`REMINDER_DB_PATH`** (по умолчанию `data/reminders.sqlite3`).
- Фоновая проверка ~каждые **15 секунд**; сообщение уходит в **тот же личный чат**, где создано напоминание.
- То же напоминание можно задать **обычной фразой** в личку (см. выше «Обычный текст без `/`»): intent `create_reminder` + **dateparser** по полю `datetime_text` из JSON.

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
│   │   ├── assistant_dm.py
│   │   ├── cloud_commands.py
│   │   ├── new_message.py
│   │   ├── owner_ask.py
│   │   ├── reminder_command.py
│   │   └── search_command.py
│   └── services/
│       ├── forwarder.py
│       ├── filter_service.py
│       ├── llm_router.py
│       ├── llm_service.py
│       ├── openrouter_service.py
│       ├── reminder_loop.py
│       ├── reminder_store.py
│       ├── storage.py
│       └── web_search_service.py
├── deploy/
│   └── telegram-assistant.service.example
├── prompts/
│   ├── intent_parser.txt
│   └── message_analyzer.txt
├── .env.example
├── requirements.txt
└── README.md
```

## Важно

- Убедитесь, что аккаунт **уже вступил** в источники/цели (каналы/группы), иначе Telethon не сможет читать/писать туда.
- Соблюдайте правила Telegram и законодательство; этот проект — инфраструктура, ответственность за использование на вас.
