import psycopg2
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort,
)
from db import get_db
from utils import login_required

channels_bp = Blueprint("channels", __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _require_workspace_member(db, ws_id, user_id):
    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (ws_id, user_id),
        )
        if not cur.fetchone():
            abort(403)


def _require_channel_member(db, ch_id, user_id):
    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM channel_members WHERE channel_id = %s AND user_id = %s",
            (ch_id, user_id),
        )
        if not cur.fetchone():
            abort(403)


# ── GET /workspaces/<ws_id>/channels ─────────────────────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels")
@login_required
def list_channels(ws_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        ws = cur.fetchone()
        if not ws:
            abort(404)
        workspace = {"workspace_id": ws[0], "name": ws[1]}

        # Channels the user has joined (non-DM only)
        cur.execute(
            """
            SELECT c.channel_id, c.name, c.channel_type,
                   (SELECT COUNT(*) FROM channel_members cm2
                    WHERE cm2.channel_id = c.channel_id) AS member_count
            FROM channels c
            JOIN channel_members cm ON c.channel_id = cm.channel_id AND cm.user_id = %s
            WHERE c.workspace_id = %s AND c.channel_type != 'direct'
            ORDER BY c.channel_type, c.name
            """,
            (user_id, ws_id),
        )
        joined_channels = [
            {"channel_id": r[0], "name": r[1], "channel_type": r[2], "member_count": r[3]}
            for r in cur.fetchall()
        ]

        # Public channels the user has NOT joined
        cur.execute(
            """
            SELECT c.channel_id, c.name,
                   (SELECT COUNT(*) FROM channel_members cm2
                    WHERE cm2.channel_id = c.channel_id) AS member_count
            FROM channels c
            WHERE c.workspace_id = %s AND c.channel_type = 'public'
              AND NOT EXISTS (
                  SELECT 1 FROM channel_members cm
                  WHERE cm.channel_id = c.channel_id AND cm.user_id = %s
              )
            ORDER BY c.name
            """,
            (ws_id, user_id),
        )
        available_channels = [
            {"channel_id": r[0], "name": r[1], "member_count": r[2]}
            for r in cur.fetchall()
        ]

    return render_template(
        "channels/list.html",
        workspace=workspace,
        joined_channels=joined_channels,
        available_channels=available_channels,
    )


# ── GET/POST /workspaces/<ws_id>/channels/new ─────────────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/new", methods=["GET", "POST"])
@login_required
def new_channel(ws_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        ws = cur.fetchone()
        if not ws:
            abort(404)
        workspace = {"workspace_id": ws[0], "name": ws[1]}

    if request.method == "GET":
        return render_template("channels/new.html", workspace=workspace)

    name = request.form.get("name", "").strip()
    channel_type = request.form.get("channel_type", "").strip()

    if not name:
        flash("Channel name is required.", "error")
        return render_template("channels/new.html", workspace=workspace), 422

    if channel_type not in ("public", "private"):
        flash("Channel type must be public or private.", "error")
        return render_template("channels/new.html", workspace=workspace), 422

    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM channels
               WHERE workspace_id = %s AND name = %s AND channel_type != 'direct'""",
            (ws_id, name),
        )
        if cur.fetchone():
            flash(f"A channel named '{name}' already exists in this workspace.", "error")
            return render_template("channels/new.html", workspace=workspace), 422

    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO channels (workspace_id, name, channel_type, created_by)
                   VALUES (%s, %s, %s, %s) RETURNING channel_id""",
                (ws_id, name, channel_type, user_id),
            )
            ch_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO channel_members (channel_id, workspace_id, user_id, joined_at)
                   VALUES (%s, %s, %s, NOW())""",
                (ch_id, ws_id, user_id),
            )
        db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        flash("A channel with that name already exists in this workspace.", "error")
        return render_template("channels/new.html", workspace=workspace), 422
    except Exception:
        db.rollback()
        raise

    return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))


# ── POST /workspaces/<ws_id>/dm/new ──────────────────────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/dm/new", methods=["POST"])
@login_required
def new_dm(ws_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)

    try:
        target_user_id = int(request.form.get("target_user_id", ""))
    except (ValueError, TypeError):
        flash("Invalid user.", "error")
        return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))

    if target_user_id == user_id:
        flash("You cannot send a direct message to yourself.", "error")
        return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))

    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (ws_id, target_user_id),
        )
        if not cur.fetchone():
            flash("That user is not an active member of this workspace.", "error")
            return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))

    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO channels (workspace_id, name, channel_type, created_by)
                   VALUES (%s, NULL, 'direct', %s) RETURNING channel_id""",
                (ws_id, user_id),
            )
            ch_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO channel_members (channel_id, workspace_id, user_id, joined_at)
                   VALUES (%s, %s, %s, NOW())""",
                (ch_id, ws_id, user_id),
            )
            # Trigger fires on this second insert — raises if duplicate DM pair
            cur.execute(
                """INSERT INTO channel_members (channel_id, workspace_id, user_id, joined_at)
                   VALUES (%s, %s, %s, NOW())""",
                (ch_id, ws_id, target_user_id),
            )
        db.commit()
    except psycopg2.Error:
        db.rollback()
        flash("A direct message channel already exists with this user.", "error")
        return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))

    return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))


# ── GET /workspaces/<ws_id>/channels/<ch_id> ──────────────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/<int:ch_id>")
@login_required
def channel_detail(ws_id, ch_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)
    _require_channel_member(db, ch_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        ws = cur.fetchone()
        if not ws:
            abort(404)
        workspace = {"workspace_id": ws[0], "name": ws[1]}

        cur.execute(
            """SELECT channel_id, name, channel_type, created_at, created_by
               FROM channels WHERE channel_id = %s AND workspace_id = %s""",
            (ch_id, ws_id),
        )
        ch = cur.fetchone()
        if not ch:
            abort(404)
        channel = {
            "channel_id": ch[0], "name": ch[1], "channel_type": ch[2],
            "created_at": ch[3], "created_by": ch[4],
        }

        cur.execute(
            """SELECT m.message_id, m.body, m.posted_at,
                      u.user_id, u.username, u.nickname
               FROM messages m
               JOIN users u ON u.user_id = m.user_id
               WHERE m.channel_id = %s
               ORDER BY m.posted_at ASC, m.message_id ASC""",
            (ch_id,),
        )
        messages_raw = cur.fetchall()

        cur.execute(
            """SELECT u.user_id, u.username, u.nickname,
                      (SELECT 1 FROM workspace_admins wa
                       WHERE wa.workspace_id = %s AND wa.user_id = u.user_id) IS NOT NULL AS is_ws_admin
               FROM channel_members cm
               JOIN users u ON u.user_id = cm.user_id
               WHERE cm.channel_id = %s
               ORDER BY u.username""",
            (ws_id, ch_id),
        )
        channel_members = [
            {"user_id": r[0], "username": r[1], "nickname": r[2], "is_ws_admin": r[3]}
            for r in cur.fetchall()
        ]

        # Sidebar: all channels this user belongs to in the workspace
        cur.execute(
            """SELECT c.channel_id, c.name, c.channel_type,
                      CASE WHEN c.channel_type = 'direct' THEN
                          (SELECT u2.username FROM channel_members cm2
                           JOIN users u2 ON u2.user_id = cm2.user_id
                           WHERE cm2.channel_id = c.channel_id AND cm2.user_id != %s
                           LIMIT 1)
                      END AS dm_partner
               FROM channels c
               JOIN channel_members cm ON c.channel_id = cm.channel_id AND cm.user_id = %s
               WHERE c.workspace_id = %s
               ORDER BY c.channel_type, c.name NULLS LAST""",
            (user_id, user_id, ws_id),
        )
        sidebar_channels = [
            {"channel_id": r[0], "name": r[1], "channel_type": r[2], "dm_partner": r[3]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT 1 FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
            (ws_id, user_id),
        )
        is_ws_admin = cur.fetchone() is not None

    # Preprocess messages: date dividers + consecutive-user grouping
    messages = []
    for i, r in enumerate(messages_raw):
        msg = {
            "message_id": r[0], "body": r[1], "posted_at": r[2],
            "user_id": r[3], "username": r[4], "nickname": r[5],
        }
        msg["show_date"] = (
            i == 0 or messages_raw[i - 1][2].date() != r[2].date()
        )
        msg["is_continuation"] = (
            i > 0
            and not msg["show_date"]
            and messages_raw[i - 1][3] == r[3]
        )
        messages.append(msg)

    # DM partner name (for display in header / compose placeholder)
    dm_partner = None
    if channel["channel_type"] == "direct":
        for m in channel_members:
            if m["user_id"] != user_id:
                dm_partner = m["username"]
                break

    return render_template(
        "channels/detail.html",
        workspace=workspace,
        channel=channel,
        messages=messages,
        channel_members=channel_members,
        sidebar_channels=sidebar_channels,
        is_ws_admin=is_ws_admin,
        is_channel_creator=(channel["created_by"] == user_id),
        dm_partner=dm_partner,
        current_user_id=user_id,
    )


# ── POST /workspaces/<ws_id>/channels/<ch_id>/message ────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/<int:ch_id>/message", methods=["POST"])
@login_required
def post_message(ws_id, ch_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)
    _require_channel_member(db, ch_id, user_id)

    body = request.form.get("body", "").strip()
    if not body:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (channel_id, user_id, body) VALUES (%s, %s, %s)",
            (ch_id, user_id, body),
        )
    db.commit()

    return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))


# ── POST /workspaces/<ws_id>/channels/<ch_id>/join ───────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/<int:ch_id>/join", methods=["POST"])
@login_required
def join_channel(ws_id, ch_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "SELECT channel_type FROM channels WHERE channel_id = %s AND workspace_id = %s",
            (ch_id, ws_id),
        )
        ch = cur.fetchone()
        if not ch:
            abort(404)
        # HARD RULE — abort immediately for any non-public channel
        if ch[0] != "public":
            abort(403)

        cur.execute(
            "SELECT 1 FROM channel_members WHERE channel_id = %s AND user_id = %s",
            (ch_id, user_id),
        )
        if cur.fetchone():
            return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO channel_members (channel_id, workspace_id, user_id, joined_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (channel_id, user_id) DO NOTHING""",
                (ch_id, ws_id, user_id),
            )
        db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))


# ── POST /workspaces/<ws_id>/channels/<ch_id>/leave ──────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/<int:ch_id>/leave", methods=["POST"])
@login_required
def leave_channel(ws_id, ch_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)
    _require_channel_member(db, ch_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM channel_members WHERE channel_id = %s AND user_id = %s",
            (ch_id, user_id),
        )
    db.commit()

    return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))


# ── POST /workspaces/<ws_id>/channels/<ch_id>/invite ─────────────────────────

@channels_bp.route("/workspaces/<int:ws_id>/channels/<int:ch_id>/invite", methods=["POST"])
@login_required
def invite_to_channel(ws_id, ch_id):
    user_id = session["user_id"]
    db = get_db()

    _require_workspace_member(db, ws_id, user_id)

    with db.cursor() as cur:
        cur.execute(
            "SELECT channel_type, created_by FROM channels WHERE channel_id = %s AND workspace_id = %s",
            (ch_id, ws_id),
        )
        ch = cur.fetchone()
        if not ch:
            abort(404)
        if ch[0] != "private":
            abort(403)
        if ch[1] != user_id:
            abort(403)

    try:
        target_user_id = int(request.form.get("target_user_id", ""))
    except (ValueError, TypeError):
        flash("Invalid user.", "error")
        return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (ws_id, target_user_id),
        )
        if not cur.fetchone():
            flash("That user is not an active member of this workspace.", "error")
            return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

        cur.execute(
            "SELECT 1 FROM channel_members WHERE channel_id = %s AND user_id = %s",
            (ch_id, target_user_id),
        )
        if cur.fetchone():
            flash("That user is already a member of this channel.", "error")
            return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

        cur.execute(
            """SELECT 1 FROM channel_invitations
               WHERE channel_id = %s AND invitee_id = %s AND status = 'pending'""",
            (ch_id, target_user_id),
        )
        if cur.fetchone():
            flash("A pending invitation already exists for that user.", "error")
            return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO channel_invitations (channel_id, inviter_id, invitee_id, status)
                   VALUES (%s, %s, %s, 'pending')""",
                (ch_id, user_id, target_user_id),
            )
        db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        flash("A pending invitation already exists for that user in this channel.", "error")
        return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))

    flash("Invitation sent.", "success")
    return redirect(url_for("channels.channel_detail", ws_id=ws_id, ch_id=ch_id))
