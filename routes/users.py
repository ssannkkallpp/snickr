from flask import Blueprint, request, jsonify, session
from db import get_db
from utils import login_required

users_bp = Blueprint("users", __name__)


# ── GET /users/search?q=<email> ───────────────────────────────────────────────

@users_bp.route("/users/search")
@login_required
def search_users():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({})

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT user_id, username, nickname FROM users WHERE email = %s",
            (q,),
        )
        row = cur.fetchone()

    if row is None:
        return jsonify({})

    return jsonify({"user_id": row[0], "username": row[1], "nickname": row[2]})


# ── GET /workspaces/<ws_id>/members/search?q=<query> ─────────────────────────
# Powers the channel invite dropdown and DM search in the channel detail UI.
# Returns [] (not 403) for non-members to avoid leaking workspace existence.

@users_bp.route("/workspaces/<int:ws_id>/members/search")
@login_required
def members_search(ws_id):
    user_id = session["user_id"]
    db = get_db()

    # Silently return empty for non-members
    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s""",
            (ws_id, user_id),
        )
        if not cur.fetchone():
            return jsonify([])

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    pattern = f"%{q}%"
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT u.user_id, u.username, u.nickname
            FROM users u
            JOIN workspace_members wm ON u.user_id = wm.user_id
            WHERE wm.workspace_id = %s
              AND wm.user_id != %s
              AND (u.username ILIKE %s OR u.nickname ILIKE %s)
            ORDER BY u.username
            LIMIT 10
            """,
            (ws_id, user_id, pattern, pattern),
        )
        results = [
            {"user_id": r[0], "username": r[1], "nickname": r[2]}
            for r in cur.fetchall()
        ]

    return jsonify(results)
