# Telegram user-assistant (Telethon)

User-client (не BotFather-бот): отдельный Telegram-аккаунт через **Telethon** слушает указанные чаты/каналы, фильтрует сообщения по ключевым словам, при необходимости **пересылает оригинал** и/или отправляет **переработанный текст** из локальной LLM (**Ollama**) в целевые чаты.

## Требования

- Python **3.11+**
- Аккаунт Telegram + `API_ID` / `API_HASH` с [my.telegram.org](https://my.telegram.org)
- Для режима LLM: запущенный Ollama (локально или на Mac mini по Tailscale, endpoint `/api/generate`)

## Установка

```bash
cd telegram_user_assistant
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env` (минимум `API_ID`, `API_HASH`). Для личного чат-ассистента достаточно `ASK_SENDER_IDS`; для мониторинга каналов добавьте `TARGET_CHATS` и источники: `SOURCE_CHATS` и/или `SOURCE_KEYWORD_RULES`, плюс ключевые слова — см. ниже.

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

### Smoke-check после обновления на сервере

После `git pull` и restart быстро проверьте основной контур в личке ассистента:

```text
/health
цена btc
напомни через 1 минуту тест
покажи напоминания
отмени #ID
покажи историю напоминаний
```

Ожидаемо: `/health` видит Ollama и модель, цена приходит через Binance, напоминание появляется в списке, `отмени #ID` убирает его из активных, а история показывает статус `отменено`.

## Команда `/ask` в личке (разрешённые отправители)

В `.env` задайте **`ASK_SENDER_IDS`** — JSON-массив **числовых user id** Telegram-аккаунтов, с которых разрешено писать `/ask` ассистенту в **личку** (например, ваш второй аккаунт). Узнать id: `@userinfobot` и т.п.

Пример:

```env
ASK_SENDER_IDS=[123456789,987654321]
```

Поведение:

- Только **входящие** личные сообщения от user id из этого списка.
- Сообщение **`?`** — краткая памятка по доступным командам (удобно закрепить в чате).
- Команда **`/ask текст`** — текст уходит в Ollama (`LLM_API_URL`, `LLM_MODEL`), ответ приходит в тот же чат. **Без live-данных** (цены, новости) — для этого есть **`/price`** и **`/search`**.
- **`/price btc`** — актуальная цена криптовалюты через Binance public API (не LLM, ключ не нужен).
- **`/search запрос`** — интернет-поиск Tavily + краткая сводка на русском.
- **`/health`** — healthcheck сервера, Ollama/Tailscale, LLM timeout'ов и provider/cloud лимитов.
- **Обычный текст без `/`** — сначала детерминированные парсеры цены крипты и частых напоминаний, иначе **intent** через локальную Qwen (`prompts/intent_parser.txt`): напоминание, цена крипты, LLM, web search, cloud. Если текст похож на действие, но JSON intent не распознан безопасно, ассистент попросит уточнить вместо свободного ответа модели.
- Разговорное управление напоминаниями без команды: «напомни завтра в 10 проверить сервер», «напомни через 30 минут проверить сервер», «покажи напоминания», «покажи историю напоминаний», «отмени #12», «отмени первое».
- Разговорные служебные действия: «проверь здоровье», «доступна ли Ollama?», «как сервер?», «какая модель используется?», «покажи каналы», «покажи группы», «подпишись на @channel». Подписка на канал через обычный текст требует подтверждения «да».
- Если написать **`/ask напомни ...`** или **`/ask как сервер?`**, ассистент сначала попробует выполнить действие, а не отправлять это как обычный вопрос модели.
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

По умолчанию ассистент использует **локальную Qwen через Ollama** (`LLM_API_URL`, `LLM_MODEL`). Это основной режим для `/ask`, coding-задач, routing/intent parser и напоминаний. Ответы пользователю — **на русском**; список возможностей для модели — в `prompts/assistant_capabilities.txt` (тот же текст, что в `?`).

Если Telegram-ассистент запущен на сервере, а Ollama работает на Mac mini, подключите оба устройства к Tailscale и укажите Tailscale IP Mac mini в `.env` на сервере:

```env
LLM_MODEL=qwen3.5-ru-assistant
LLM_API_URL=http://TAILSCALE_IP_MAC_MINI:11434/api/generate
LLM_THINK=false
LLM_TIMEOUT=120
LLM_INTENT_TIMEOUT=20
LLM_ANALYZE_TIMEOUT=300
```

`LLM_THINK=false` отправляет в Ollama `"think": false`, чтобы обычные ответы приходили быстрее и без thinking-текста наружу. Для проверки с сервера:

```bash
curl http://TAILSCALE_IP_MAC_MINI:11434/api/generate -d '{
  "model": "qwen3.5-ru-assistant",
  "prompt": "Привет. Ответь коротко по-русски.",
  "stream": false,
  "think": false
}'
```

**Важно:** `/ask` не имеет доступа к актуальным ценам и новостям. Для цены крипты — **`/price btc`** или фраза «цена биткоина». Для интернета — **`/search запрос`**.

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
MAX_CLOUD_REQUESTS_PER_DAY=30
LOG_CLOUD_USAGE=true
CLOUD_USAGE_DB_PATH=data/cloud_usage.sqlite3
```

Успешные запросы к OpenRouter считаются в SQLite по UTC-дате. Если дневной лимит `MAX_CLOUD_REQUESTS_PER_DAY` исчерпан или равен `0`, cloud-запросы не отправляются.

Команда **`/provider`** показывает текущие модели и режимы.

## Web Search Mode

Команда:

```text
/search новости Ethereum сегодня
```

Провайдер **Tavily** (`app/services/web_search_service.py`). Результаты (`title`, `url`, `snippet`, дата публикации при наличии) сводятся через OpenRouter. По умолчанию поиск настроен на более свежие и релевантные результаты: `advanced`, `time_range=month`, больше источников и строгая сводка с учетом дат.

```env
ENABLE_WEB_SEARCH=true
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=tvly-...
WEB_SEARCH_DEPTH=advanced
WEB_SEARCH_TOPIC=general
WEB_SEARCH_TIME_RANGE=month
WEB_SEARCH_AUTO_PARAMETERS=true
WEB_SEARCH_CHUNKS_PER_SOURCE=3
WEB_SEARCH_MAX_RESULTS=8
WEB_SEARCH_TIMEOUT=30
```

Для максимально свежих новостей можно поставить `WEB_SEARCH_TOPIC=news` и `WEB_SEARCH_TIME_RANGE=day` или `week`. `WEB_SEARCH_DEPTH=advanced` обычно качественнее, но расходует больше Tavily credits, чем `basic`.

Если `ENABLE_WEB_SEARCH=false`, `/search` ответит, что режим отключён. При включённом поиске, но пустом ответе Tavily, бот попробует ответить через `/cloud` (нужен OpenRouter). Сводка результатов — **на русском**; если OpenRouter недоступен, придёт список источников на русском.

## Crypto Price Mode (`/price`)

Команда и естественные фразы без `/` (только для `ASK_SENDER_IDS`):

```text
/price btc
/price eth
цена биткоина
сколько стоит eth
курс sol
btc
```

**Binance** public market data (`app/services/crypto_price_service.py`). **API key не нужен.** Пары к **USDT** (например `BTCUSDT`). CoinGecko **не используется**.

```env
ENABLE_CRYPTO_PRICE=true
BINANCE_BASE_URL=https://api.binance.com
BINANCE_TIMEOUT=30
DEFAULT_CRYPTO_VS_CURRENCY=usdt
```

Поддерживаемые алиасы: btc/bitcoin/биткоин, eth/эфир, sol, ton/тон, bnb, xrp, doge, ada, trx, ltc, avax, link, dot, matic.

**`/ask цена биткоина`** — обычный вопрос к локальной Qwen (без live-data). Для актуальной цены: **`/price btc`** или просто **«цена btc»**.

## Privacy Notes

- **`OPENROUTER_API_KEY`**, **`WEB_SEARCH_API_KEY`** — только в `.env`, **не коммитьте в Git** и не логируйте.
- **`/price`** / Binance — публичный API без ключа; в логах не пишутся полные тексты личных сообщений.
- Приватные Telegram-сообщения по умолчанию обрабатываются локально (`/ask`, напоминания).
- Внешние API вызываются по явной команде или intent: **`/search`** / Tavily, **`/price`** / Binance, **`/cloud`**, **`/analyze`**, intent `web_search`/`cloud_ask`/`deep_analysis`, или **`ENABLE_CLOUD_FALLBACK=true`**.
- Если включены daily summaries и **`SUMMARY_USE_CLOUD_FINAL=true`**, финальный слой ежедневной выжимки отправляется в OpenRouter автоматически; для полностью локальной обработки поставьте **`SUMMARY_USE_CLOUD_FINAL=false`**.
- Не отправляйте в OpenRouter/Tavily приватные данные, если не хотите отдавать их внешним провайдерам.

## Daily Summaries

Ассистент может без команд делать ежедневные выжимки выбранных чатов и присылать их в отдельный чат. Это отдельный список, не связанный с `SOURCE_CHATS` и keyword-фильтрами.

Поведение:

- весь день сохраняются только текст и метаданные сообщений из `SUMMARY_CHATS`;
- медиа не скачиваются;
- каждый день в `SUMMARY_TIME` по `SUMMARY_TZ` отправляется отдельная выжимка по каждому чату;
- период считается от прошлого успешного запуска, а при первом запуске — за последние 24 часа;
- если важных событий нет, приходит выжимка с текстом «Существенных событий не было»;
- старые сырые сообщения удаляются автоматически.

Настройки:

```env
ENABLE_DAILY_SUMMARY=true
SUMMARY_CHATS=["-1001234567890","some_group"]
SUMMARY_TARGET_CHAT=-1009876543210
SUMMARY_TIME=21:00
SUMMARY_TZ=Europe/Moscow
SUMMARY_DB_PATH=data/chat_summaries.sqlite3

SUMMARY_RETENTION_DAYS=7
SUMMARY_MAX_DB_MB=500
SUMMARY_STORE_MEDIA=false
SUMMARY_VACUUM_AFTER_CLEANUP=true
SUMMARY_MAX_MESSAGE_CHARS=4000

SUMMARY_USE_CLOUD_FINAL=true
SUMMARY_CLOUD_MODEL=openai/gpt-4.1-mini
SUMMARY_MAX_CLOUD_INPUT_CHARS=30000
SUMMARY_MAX_OUTPUT_TOKENS=1800
```

Локальная Qwen делает основную работу: разбивает чат на фрагменты, извлекает главное, задачи, решения, вопросы и обновляет короткую память чата. Если `SUMMARY_USE_CLOUD_FINAL=true`, OpenRouter используется только для финального слоя выжимки; при ошибке облака ассистент отправит локальный результат.

Формат сообщения:

```text
Выжимка: <название чата>
Период: 16.05 21:00 - 17.05 21:00 Europe/Moscow
Сообщений: 184

Главное:
- ...

Решения:
- ...

Задачи:
- ...

Вопросы без ответа:
- ...

Ссылки:
- ...
```

Для маленького диска рекомендуется оставить `SUMMARY_RETENTION_DAYS=7` и `SUMMARY_MAX_DB_MB=500`. Итоговые daily summaries и `chat_memory` маленькие; чистятся в первую очередь сырые сообщения.

## Script Health Digest

Отдельный режим для сообщений от скриптов вида:

```text
❌ ERROR | ZKCodex Arc Testnet
Действие: GM
35 - 0x49f139...158288 - 2026-05-23 14:12
```

Ассистент парсит статус (`OK`/`ERROR`), название скрипта, действие, номер профиля, кошелек и время. Каждые `SCRIPT_DIGEST_INTERVAL_HOURS` часов он отправляет точный отчет со счетчиками: топ профилей по ошибкам, проблемные скрипты, error rate и связки `profile + script + action`, которые нужно проверить.

Настройки:

```env
ENABLE_SCRIPT_DIGEST=true
SCRIPT_DIGEST_CHATS=["-1001234567890"]
SCRIPT_DIGEST_TARGET_CHAT=
SCRIPT_DIGEST_INTERVAL_HOURS=12
SCRIPT_DIGEST_TZ=Europe/Moscow
SCRIPT_DIGEST_DB_PATH=data/script_runs.sqlite3
SCRIPT_DIGEST_RETENTION_DAYS=30
SCRIPT_DIGEST_TOP_LIMIT=10
```

Если `SCRIPT_DIGEST_TARGET_CHAT` пустой, отчет отправляется в первый чат из `SCRIPT_DIGEST_CHATS`, то есть можно получать отчет там же, куда скрипты пишут статусы. Этот режим не использует LLM и OpenRouter: все считается регулярками и SQLite.

## Примеры команд

```text
?
/ask как сделать docker compose?
/price btc
/price eth
/search последние новости Ethereum
цена биткоина
сколько стоит sol
/cloud объясни сложную ошибку
/analyze <текст>
/provider
/join @channel1 @channel2
перешли пост в scam-группу → /check
/dialogs
/dialogs channels
```

## Подписка на каналы `/join`

Только для `ASK_SENDER_IDS`. Подписывает **аккаунт Telethon** (тот, под которым запущен ассистент), не «любой чат».

```text
/join @crypto_news @another_channel
/join https://t.me/some_channel
/join https://t.me/+InviteHash
```

За одну команду — **не больше 3** каналов. Пауза между join ~1.5 с (меньше риск лимитов Telegram).

После подписки канал можно добавить в `SOURCE_CHATS` для мониторинга (вручную в `.env` или через `/dialogs channels`).

## Scam-check группа (ручная проверка постов)

Только для `ASK_SENDER_IDS`. **Не в личке** и **не в других группах** — только в чате `SCAM_CHECK_GROUP_ID`. Это экономит токены и не путает обычные фразы со словом «пост».

### Настройка

1. Создайте отдельную Telegram-группу (например «Scam Check»).
2. Добавьте туда аккаунт ассистента (Telethon).
3. Узнайте ID группы: `/dialogs groups` → скопируйте `ID: -100...`.
4. В `.env`:

```env
ENABLE_MANUAL_SCAM_CHECK=true
SCAM_CHECK_GROUP_ID=-1001234567890
ENABLE_LINK_SCAM_CHECK=false
ENABLE_WEB_SEARCH=true
WEB_SEARCH_API_KEY=...
OPENROUTER_API_KEY=...
SCAM_CHECK_MAX_LINKS=5
SCAM_CHECK_MAX_SEARCHES_PER_LINK=2
SCAM_CHECK_PENDING_TTL_MINUTES=60
```

5. Перезапуск: `sudo systemctl restart telegram-assistant.service`

### Использование

**Автоматически (по умолчанию):** отправьте в группу сообщение **со ссылкой** (URL, `t.me/...`, `@channel`) — бот сразу начнёт проверку.

**Вручную:** перешлите пост **без ссылок** → «Пост сохранил…», затем `/check` или `проверь пост` (пост хранится **60 минут**).

Триггеры в группе: `/check`, `проверь пост`, `проверь ссылки`, `это скам?`, `скам?`.

```env
SCAM_CHECK_AUTO_ON_LINK=true
```

Ассистент извлечёт ссылки (включая скрытые `MessageEntityTextUrl`), при Tavily — поиск `{domain} scam` / `phishing crypto`, затем **OpenRouter** на русском (SAFE / SUSPICIOUS / SCAM / UNKNOWN).

### Поведение вне группы

| Где написали | Ответ |
|--------------|--------|
| Личка: «проверь пост» / `/check` | «Перешли пост в специальную группу…» |
| Другая группа | «Проверка постов доступна только в специальной группе.» |
| `SCAM_CHECK_GROUP_ID` пустой | «SCAM_CHECK_GROUP_ID не задан в .env.» |

Вне scam-группы **не вызываются** OpenRouter, Tavily и web search для проверки.

**Важно:** проверка **не гарантирует** безопасность. Не подключайте wallet и не подписывайте транзакции только на основе AI. **Seed phrase / private key** никогда нельзя вводить. Бот **не открывает** ссылки и не скачивает файлы.

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
/remind history
/remind list all
/remind cancel 3
```

- База напоминаний: **`REMINDER_DB_PATH`** (по умолчанию `data/reminders.sqlite3`).
- Фоновая проверка ~каждые **15 секунд**; сообщение уходит в **тот же личный чат**, где создано напоминание.
- Активные напоминания имеют статус `active`, отменённые — `cancelled`, доставленные — `fired`; история не удаляется физически при обычной отмене/доставке.
- То же напоминание можно задать **обычной фразой** в личку (см. выше «Обычный текст без `/`»). Частые форматы обрабатываются без LLM, остальные идут через intent `create_reminder` + **dateparser** по полю `datetime_text` из JSON.

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

## Разные ключевые слова и получатели для разных чатов

Для удобного редактирования задайте **`SOURCE_KEYWORD_RULES_FILE`** — путь к JSON-файлу с правилами. Путь относительный от корня проекта, если не указан абсолютный.

```env
SOURCE_KEYWORD_RULES_FILE=config/source_keyword_rules.json
SOURCE_KEYWORD_RULES=
```

Сам файл `config/source_keyword_rules.json`:

```json
[
  {
    "source": "channel_a",
    "keywords": ["релиз", "release"],
    "targets": ["me"]
  },
  {
    "source": "-1001234567890",
    "keywords": ["CVE", "уязвимость"],
    "targets": ["-1009876543210"]
  }
]
```

Для маленьких конфигов можно по-прежнему использовать **`SOURCE_KEYWORD_RULES`** прямо в `.env` одной строкой. Формат тот же: JSON-массив объектов с полями `source`, `keywords` и необязательным `targets`. Если задан `SOURCE_KEYWORD_RULES_FILE`, он имеет приоритет.

Можно задать несколько правил для одного источника, чтобы разные слова уходили в разные чаты.

Подписка на новые сообщения идёт по **объединению** `SOURCE_CHATS` и всех `source` из правил (дубликаты убираются).

Поведение:

- Если для чата есть правило в `SOURCE_KEYWORD_RULES` — используются **только** его `keywords` (глобальный `FILTER_KEYWORDS` для этого чата не применяется).
- Если чат указан **только** в `SOURCE_CHATS` и под него **нет** правила — действует **`FILTER_KEYWORDS`** (общий список).
- Если правило содержит `targets` — исходное сообщение и LLM-ответ отправляются в эти чаты.
- Если правило не содержит `targets` — используется общий `TARGET_CHATS`.
- Можно комбинировать: часть чатов с отдельными правилами, часть — под общий `FILTER_KEYWORDS`.

Если `SOURCE_KEYWORD_RULES_FILE` и `SOURCE_KEYWORD_RULES` не заданы, работает только глобальный **`FILTER_KEYWORDS`**, как раньше.

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
│   │   ├── check_post_command.py
│   │   ├── scam_check_access.py
│   │   ├── cloud_commands.py
│   │   ├── dialogs.py
│   │   ├── join_command.py
│   │   ├── new_message.py
│   │   ├── owner_ask.py
│   │   ├── owner_commands.py
│   │   ├── pending_post_handler.py
│   │   ├── price_command.py
│   │   ├── reminder_command.py
│   │   └── search_command.py
│   └── services/
│       ├── channel_join_service.py
│       ├── crypto_price_parser.py
│       ├── crypto_price_service.py
│       ├── link_extractor.py
│       ├── pending_post_store.py
│       ├── scam_check_service.py
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
│   ├── assistant_capabilities.txt
│   ├── intent_parser.txt
│   ├── message_analyzer.txt
│   └── scam_check_analysis.txt
├── .env.example
├── requirements.txt
└── README.md
```

## Важно

- Убедитесь, что аккаунт **уже вступил** в источники/цели (каналы/группы), иначе Telethon не сможет читать/писать туда.
- Соблюдайте правила Telegram и законодательство; этот проект — инфраструктура, ответственность за использование на вас.
