# vacantion_bot

Telegram bot for finding nearby vacancies by user geolocation.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create `.env` in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
SEARCH_RADIUS_KM=10
```

## Run

Initialize or migrate the SQLite database:

```powershell
python init_db.py
```

Import vacancies from `vacancies.xlsx`:

```powershell
python import_excel.py
```

Start the bot:

```powershell
python bot.py
```

## Data

`vacancies.xlsx` must contain these columns:

- `title`
- `address`
- `latitude`
- `longitude`

Optional columns:

- `project`
- `description`
- `description_2`
- `maps`
- `payment`

The bot stores vacancies and responses in local SQLite database `vacancies.db`.
Do not commit `.env` or local database files to git.
