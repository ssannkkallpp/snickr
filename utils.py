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


def get_bookmark_groups():
    user_id = session.get("user_id")
    if not user_id:
        return []
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT w.workspace_id, w.name,
                       c.channel_id, c.name, c.channel_type,
                       CASE WHEN c.channel_type = 'direct' THEN
                           (SELECT u.username FROM channel_members cm2
                            JOIN users u ON u.user_id = cm2.user_id
                            WHERE cm2.channel_id = c.channel_id AND cm2.user_id != %s
                            LIMIT 1)
                       END AS dm_partner
                FROM channel_bookmarks cb
                JOIN channels   c ON c.channel_id   = cb.channel_id
                JOIN workspaces w ON w.workspace_id = c.workspace_id
                WHERE cb.user_id = %s
                ORDER BY w.name, c.channel_type, c.name NULLS LAST
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()
    except Exception:
        return []

    groups = {}
    for ws_id, ws_name, ch_id, ch_name, ch_type, dm_partner in rows:
        if ws_id not in groups:
            groups[ws_id] = {
                "workspace_id": ws_id,
                "workspace_name": ws_name,
                "channels": [],
            }
        groups[ws_id]["channels"].append({
            "channel_id": ch_id,
            "name": ch_name,
            "channel_type": ch_type,
            "dm_partner": dm_partner,
        })
    return list(groups.values())
