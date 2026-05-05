import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_NAME = os.environ.get("DB_NAME", "snickr")
    DB_USER = os.environ.get("DB_USER", "postgres")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
