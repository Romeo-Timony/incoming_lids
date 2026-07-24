# incoming_lids

Telegram-бот для опроса клиента перед записью на массаж.

Схема:

- `@massagebot1_bot` — опрашивает клиента и собирает анкету;
- `@massagebot2_bot` — отправляет готовую заявку администратору.

## Что собирает ассистент

- имя клиента;
- контакт;
- жалобу на здоровье;
- где болит;
- силу боли (слабая / средняя / сильная);
- как давно беспокоит;
- желаемое время записи.

## Структура проекта

```text
incoming_lids/
├── bot/
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── support.py
│   ├── utils/
│   │   ├── __init__.py
│   │   └── formatter.py
│   ├── __init__.py
│   └── main.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── logging.py
│   └── schemas.py
├── services/
│   ├── assistant/
│   │   ├── __init__.py
│   │   ├── openai_support_assistant.py
│   │   └── prompts.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── session_repository.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   └── operator_notifier.py
│   ├── __init__.py
│   └── workflow.py
├── .env.example
├── .gitignore
├── main.py
└── requirements.txt
```

## Как работает

1. Клиент пишет `@massagebot1_bot`.
2. Бот сохраняет сессию в памяти.
3. `OpenAISupportAssistant` получает:
   - текущее состояние анкеты;
   - новое сообщение клиента;
   - флаг первого сообщения.
4. Модель возвращает JSON:
   - ответ клиенту;
   - обновленные поля анкеты;
   - признак готовности к отправке.
5. Когда обязательные поля собраны, `@massagebot2_bot` отправляет заявку администратору.
6. Клиент получает подтверждение.

## Переменные окружения

```env
TELEGRAM_BOT_TOKEN=token_from_massagebot1_bot
OPERATOR_BOT_TOKEN=token_from_massagebot2_bot
OPERATOR_CHAT_ID=123456789
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
LOG_LEVEL=INFO
```

### Как подключить получение заявок в `@massagebot2_bot`

1. Запустите проект.
2. Откройте `@massagebot2_bot` и отправьте `/start`.
3. Бот ответит, что чат закреплён для уведомлений.
4. После этого все заполненные анкеты будут приходить сюда.

`OPERATOR_CHAT_ID` в `.env` необязателен: его можно задать вручную или получить автоматически после `/start`.

## Запуск

```powershell
cd path\to\incoming_lids
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# заполните токены и OPERATOR_CHAT_ID в .env
python main.py
```

## Важно

- Сессии хранятся в памяти процесса. После перезапуска бота история сбрасывается.
- Если у пользователя есть `@username`, бот использует его как Telegram-контакт по умолчанию.
- Клиентский бот и бот заявок — разные токены; заявки уходят через `@massagebot2_bot`.
- Токены храните только в `.env`, не коммитьте их в git.
- Для прода лучше добавить постоянное хранилище, retry/backoff и аудит сообщений.
