from flask import Blueprint, request, jsonify
from db import get_db
from utils import login_required

users_bp = Blueprint("users", __name__)


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
