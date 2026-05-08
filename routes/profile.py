from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_db
from logging_config import log_event
from utils import login_required

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]
    db = get_db()

    if request.method == "GET":
        with db.cursor() as cur:
            cur.execute(
                """SELECT user_id, email, username, nickname, created_at
                   FROM users WHERE user_id = %s""",
                (user_id,),
            )
            row = cur.fetchone()
        user = {
            "user_id": row[0], "email": row[1], "username": row[2],
            "nickname": row[3], "created_at": row[4],
        }
        return render_template("profile/view.html", user=user)

    # ── POST ────────────────────────────────────────────────────────────────────
    nickname = request.form.get("nickname", "").strip() or None
    new_password = request.form.get("new_password", "")

    def rerender():
        with db.cursor() as cur:
            cur.execute(
                "SELECT user_id, email, username, created_at FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        user = {
            "user_id": row[0], "email": row[1], "username": row[2],
            "nickname": nickname,  # preserve what the user typed
            "created_at": row[3],
        }
        return render_template("profile/view.html", user=user)

    if new_password:
        current_password = request.form.get("current_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password:
            flash("Please enter your current password to set a new one.", "error")
            return rerender()

        with db.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM users WHERE user_id = %s", (user_id,)
            )
            stored_hash = cur.fetchone()[0]

        if not check_password_hash(stored_hash, current_password):
            flash("Current password is incorrect.", "error")
            return rerender()

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return rerender()

        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return rerender()

        new_hash = generate_password_hash(new_password)
        with db.cursor() as cur:
            cur.execute(
                "UPDATE users SET nickname = %s, password_hash = %s WHERE user_id = %s",
                (nickname, new_hash, user_id),
            )
        db.commit()
        log_event("updated their profile — changed nickname and password")
    else:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE users SET nickname = %s WHERE user_id = %s",
                (nickname, user_id),
            )
        db.commit()
        log_event("updated their profile — changed nickname")

    flash("Profile updated successfully.", "success")
    return redirect(url_for("profile.profile"))
