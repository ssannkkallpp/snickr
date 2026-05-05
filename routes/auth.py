from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("workspaces.list_workspaces"))

    if request.method == "GET":
        return render_template("auth/signup.html")

    email = request.form.get("email", "").strip()
    username = request.form.get("username", "").strip()
    nickname = request.form.get("nickname", "").strip() or None
    password = request.form.get("password", "")

    if not email:
        flash("Email is required.", "error")
        return render_template("auth/signup.html"), 422
    if not username:
        flash("Username is required.", "error")
        return render_template("auth/signup.html"), 422
    if not password:
        flash("Password is required.", "error")
        return render_template("auth/signup.html"), 422

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            flash("An account with that email already exists.", "error")
            return render_template("auth/signup.html"), 422

        cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            flash("That username is already taken.", "error")
            return render_template("auth/signup.html"), 422

        password_hash = generate_password_hash(password)
        cur.execute(
            """
            INSERT INTO users (email, username, nickname, password_hash)
            VALUES (%s, %s, %s, %s)
            RETURNING user_id
            """,
            (email, username, nickname, password_hash),
        )
        user_id = cur.fetchone()[0]
    db.commit()

    session.clear()
    session["user_id"] = user_id
    return redirect(url_for("workspaces.list_workspaces"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("workspaces.list_workspaces"))

    if request.method == "GET":
        return render_template("auth/login.html")

    login_input = request.form.get("login", "").strip()
    password = request.form.get("password", "")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT user_id, password_hash FROM users WHERE email = %s OR username = %s",
            (login_input, login_input),
        )
        row = cur.fetchone()

    if row is None or not check_password_hash(row[1], password):
        flash("Invalid credentials.", "error")
        return render_template("auth/login.html"), 401

    session.clear()
    session["user_id"] = row[0]
    return redirect(url_for("workspaces.list_workspaces"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
