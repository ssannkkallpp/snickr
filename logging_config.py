import logging
import os
from logging.handlers import RotatingFileHandler

from flask import g


def init_logging(app):
    os.makedirs("logs", exist_ok=True)

    handler = RotatingFileHandler(
        "logs/snickr.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    logger = logging.getLogger("snickr")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("system server started")


def log_event(message, username=None):
    if username is None:
        user = g.get("current_user")
        username = user["username"] if user else "anon"
    logging.getLogger("snickr").info("%s %s", username, message)
