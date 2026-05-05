from functools import wraps
from flask import session, redirect, url_for, flash, g
from db import get_db


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "SELECT user_id, email, username, nickname FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {"user_id": row[0], "email": row[1], "username": row[2], "nickname": row[3]}
    except Exception:
        return None
