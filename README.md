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
MAX_BOT_TOKEN=your_max_bot_token
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

The import marks vacancies from the workbook as active. Old vacancies that are no
longer present in the workbook stay in the database for response history, but are
hidden from search and catalog.

Export all saved responses to `responses.csv`:

```powershell
python export_responses.py
```

Start the bot:

```powershell
python bot.py
```

Start the Max bot:

```powershell
python max_bot.py
```

`max_bot.py` takes vacancies from the external source in
`vacancy_api.py` (SheetDB API). Local SQLite is still used for storing responses
and for keeping a local copy of the vacancy that the user responded to.

## Data

`vacancies.xlsx` must contain these columns:

- `region`
- `city`
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
New responses are also appended to `responses.csv` so they can be opened in Excel.
Do not commit `.env` or local database files to git.

## Bot commands

- `/start` - quick search by geolocation and main menu.
- `/catalog` - choose region and city, then browse vacancies.

## Max bot commands

- `/start` - show help and available scenarios.
- `/near 55.75, 37.61` - find vacancies within 10 km by coordinates.
- `/search` - step-by-step search by city and position.
- `/respond 2` or just `2` after a vacancy list - start the questionnaire.
- `/cancel` - reset the current dialog.
