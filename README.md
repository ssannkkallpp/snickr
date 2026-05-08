# Snickr

A Slack-inspired team messaging application built with Flask and PostgreSQL.

## Prerequisites

- Python 3.10+
- PostgreSQL

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Create the database**

Create a PostgreSQL database, then load the schema:

```bash
psql -U <your_user> -d <your_database> -f schema.sql
```

**3. Configure environment variables**

Create a `.env` file in the project root:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=<your_database>
DB_USER=<your_user>
DB_PASSWORD=<your_password>
FLASK_SECRET_KEY=<any_long_random_string>
```

## Running the Application

```bash
python -m flask run --with-threads
```

The application will be available at `http://127.0.0.1:5000`.

The `--with-threads` flag is required to support live message polling across concurrent users.

## Testing with Multiple Users

To simulate multiple users simultaneously, open separate **private/incognito windows** in your browser — each maintains its own independent session. Regular tabs share cookies and will share the same logged-in session.

## Logs

Application activity is written to `logs/snickr.log`. The file rotates automatically at 2 MB, keeping the five most recent files. Log files are excluded from version control.
