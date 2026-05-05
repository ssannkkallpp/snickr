from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort,
)
from db import get_db
from utils import login_required

workspaces_bp = Blueprint("workspaces", __name__, url_prefix="/workspaces")


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_member(db, ws_id, user_id):
    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (ws_id, user_id),
        )
        return cur.fetchone() is not None


def _is_admin(db, ws_id, user_id):
    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
            (ws_id, user_id),
        )
        return cur.fetchone() is not None


# ── GET /workspaces ───────────────────────────────────────────────────────────

@workspaces_bp.route("")
@login_required
def list_workspaces():
    user_id = session["user_id"]
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT w.workspace_id, w.name, w.description,
                   (SELECT COUNT(*) FROM workspace_members wm2
                    WHERE wm2.workspace_id = w.workspace_id AND wm2.status = 'active') AS member_count,
                   (SELECT 1 FROM workspace_admins wa
                    WHERE wa.workspace_id = w.workspace_id AND wa.user_id = %s) IS NOT NULL AS is_admin
            FROM workspaces w
            JOIN workspace_members wm ON wm.workspace_id = w.workspace_id
            WHERE wm.user_id = %s AND wm.status = 'active'
            ORDER BY w.name
            """,
            (user_id, user_id),
        )
        rows = cur.fetchall()

    workspaces = [
        {"workspace_id": r[0], "name": r[1], "description": r[2],
         "member_count": r[3], "is_admin": r[4]}
        for r in rows
    ]
    return render_template("workspaces/list.html", workspaces=workspaces)


# ── GET/POST /workspaces/new ──────────────────────────────────────────────────

@workspaces_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_workspace():
    if request.method == "GET":
        return render_template("workspaces/new.html")

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None

    if not name:
        flash("Workspace name is required.", "error")
        return render_template("workspaces/new.html"), 422

    user_id = session["user_id"]
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO workspaces (name, description, created_by)
                   VALUES (%s, %s, %s) RETURNING workspace_id""",
                (name, description, user_id),
            )
            ws_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, status, joined_at)
                   VALUES (%s, %s, 'active', NOW())""",
                (ws_id, user_id),
            )
            cur.execute(
                "INSERT INTO workspace_admins (workspace_id, user_id) VALUES (%s, %s)",
                (ws_id, user_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return redirect(url_for("workspaces.workspace_detail", ws_id=ws_id))


# ── GET /workspaces/<ws_id> ───────────────────────────────────────────────────

@workspaces_bp.route("/<int:ws_id>")
@login_required
def workspace_detail(ws_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_member(db, ws_id, user_id):
        abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name, description FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        row = cur.fetchone()
        if not row:
            abort(404)
        workspace = {"workspace_id": row[0], "name": row[1], "description": row[2]}

        # Channels the user belongs to; DM rows carry the partner's username
        cur.execute(
            """
            SELECT c.channel_id, c.name, c.channel_type,
                   CASE WHEN c.channel_type = 'direct' THEN
                       (SELECT u.username FROM channel_members cm2
                        JOIN users u ON u.user_id = cm2.user_id
                        WHERE cm2.channel_id = c.channel_id AND cm2.user_id != %s
                        LIMIT 1)
                   END AS dm_partner
            FROM channels c
            JOIN channel_members cm ON c.channel_id = cm.channel_id AND cm.user_id = %s
            WHERE c.workspace_id = %s
            ORDER BY c.channel_type, c.name NULLS LAST
            """,
            (user_id, user_id, ws_id),
        )
        channels = [
            {"channel_id": r[0], "name": r[1], "channel_type": r[2], "dm_partner": r[3]}
            for r in cur.fetchall()
        ]

        # Public channels the user has NOT joined (for browse section)
        cur.execute(
            """
            SELECT c.channel_id, c.name
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
        public_channels = [{"channel_id": r[0], "name": r[1]} for r in cur.fetchall()]

        cur.execute(
            "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = %s AND status = 'active'",
            (ws_id,),
        )
        member_count = cur.fetchone()[0]

    is_admin = _is_admin(db, ws_id, user_id)

    return render_template(
        "workspaces/detail.html",
        workspace=workspace,
        channels=channels,
        public_channels=public_channels,
        member_count=member_count,
        is_admin=is_admin,
    )


# ── GET /workspaces/<ws_id>/members ──────────────────────────────────────────

@workspaces_bp.route("/<int:ws_id>/members")
@login_required
def members(ws_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_member(db, ws_id, user_id):
        abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        ws_row = cur.fetchone()
        if not ws_row:
            abort(404)
        workspace = {"workspace_id": ws_row[0], "name": ws_row[1]}

        cur.execute(
            """
            SELECT u.user_id, u.username, u.nickname, wm.joined_at,
                   (SELECT 1 FROM workspace_admins wa
                    WHERE wa.workspace_id = %s AND wa.user_id = u.user_id) IS NOT NULL AS is_admin
            FROM workspace_members wm
            JOIN users u ON u.user_id = wm.user_id
            WHERE wm.workspace_id = %s AND wm.status = 'active'
            ORDER BY wm.joined_at
            """,
            (ws_id, ws_id),
        )
        members_list = [
            {"user_id": r[0], "username": r[1], "nickname": r[2],
             "joined_at": r[3], "is_admin": r[4]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT COUNT(*) FROM workspace_admins WHERE workspace_id = %s",
            (ws_id,),
        )
        admin_count = cur.fetchone()[0]

    is_admin = _is_admin(db, ws_id, user_id)

    pending_invitations = []
    if is_admin:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT wi.invitation_id,
                       u_ee.username AS invitee_username,
                       u_ee.email    AS invitee_email,
                       u_er.username AS inviter_username,
                       wi.invited_at
                FROM workspace_invitations wi
                JOIN users u_ee ON u_ee.user_id = wi.invitee_id
                JOIN users u_er ON u_er.user_id = wi.inviter_id
                WHERE wi.workspace_id = %s AND wi.status = 'pending'
                ORDER BY wi.invited_at DESC
                """,
                (ws_id,),
            )
            pending_invitations = [
                {"invitation_id": r[0], "invitee_username": r[1], "invitee_email": r[2],
                 "inviter_username": r[3], "invited_at": r[4]}
                for r in cur.fetchall()
            ]

    return render_template(
        "workspaces/members.html",
        workspace=workspace,
        members=members_list,
        is_admin=is_admin,
        admin_count=admin_count,
        pending_invitations=pending_invitations,
        current_user_id=user_id,
    )


# ── POST /workspaces/<ws_id>/members/invite ───────────────────────────────────

@workspaces_bp.route("/<int:ws_id>/members/invite", methods=["POST"])
@login_required
def invite_member(ws_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    email = request.form.get("email", "").strip()

    with db.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        target = cur.fetchone()
        if not target:
            flash("No user found with that email address.", "error")
            return redirect(url_for("workspaces.members", ws_id=ws_id))

        target_id = target[0]

        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (ws_id, target_id),
        )
        if cur.fetchone():
            flash("That user is already a member of this workspace.", "error")
            return redirect(url_for("workspaces.members", ws_id=ws_id))

        cur.execute(
            """SELECT 1 FROM workspace_invitations
               WHERE workspace_id = %s AND invitee_id = %s AND status = 'pending'""",
            (ws_id, target_id),
        )
        if cur.fetchone():
            flash("A pending invitation already exists for that user.", "error")
            return redirect(url_for("workspaces.members", ws_id=ws_id))

        cur.execute(
            """INSERT INTO workspace_invitations
                   (workspace_id, inviter_id, invitee_id, status)
               VALUES (%s, %s, %s, 'pending')""",
            (ws_id, user_id, target_id),
        )
    db.commit()

    flash("Invitation sent.", "success")
    return redirect(url_for("workspaces.members", ws_id=ws_id))


# ── POST /workspaces/<ws_id>/members/<user_id>/remove ────────────────────────

@workspaces_bp.route("/<int:ws_id>/members/<int:target_user_id>/remove", methods=["POST"])
@login_required
def remove_member(ws_id, target_user_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    if target_user_id == user_id:
        flash("Use the Leave Workspace button to remove yourself.", "error")
        return redirect(url_for("workspaces.members", ws_id=ws_id))

    try:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM channel_members WHERE workspace_id = %s AND user_id = %s",
                (ws_id, target_user_id),
            )
            cur.execute(
                "DELETE FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
                (ws_id, target_user_id),
            )
            cur.execute(
                """UPDATE workspace_members SET status = 'removed', joined_at = NULL
                   WHERE workspace_id = %s AND user_id = %s""",
                (ws_id, target_user_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM workspaces WHERE workspace_id = %s", (ws_id,))
        workspace_exists = cur.fetchone() is not None

    if not workspace_exists:
        flash("Member removed. Workspace deleted (no members remaining).", "info")
        return redirect(url_for("workspaces.list_workspaces"))

    flash("Member removed.", "success")
    return redirect(url_for("workspaces.members", ws_id=ws_id))


# ── POST /workspaces/<ws_id>/members/<user_id>/leave ─────────────────────────

@workspaces_bp.route("/<int:ws_id>/members/<int:target_user_id>/leave", methods=["POST"])
@login_required
def leave_workspace(ws_id, target_user_id):
    user_id = session["user_id"]

    if target_user_id != user_id:
        abort(403)

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM channel_members WHERE workspace_id = %s AND user_id = %s",
                (ws_id, user_id),
            )
            cur.execute(
                "DELETE FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
                (ws_id, user_id),
            )
            cur.execute(
                """UPDATE workspace_members SET status = 'removed', joined_at = NULL
                   WHERE workspace_id = %s AND user_id = %s""",
                (ws_id, user_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    flash("You have left the workspace.", "success")
    return redirect(url_for("workspaces.list_workspaces"))


# ── POST /workspaces/<ws_id>/admins/<user_id>/add ────────────────────────────

@workspaces_bp.route("/<int:ws_id>/admins/<int:target_user_id>/add", methods=["POST"])
@login_required
def add_admin(ws_id, target_user_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    if not _is_member(db, ws_id, target_user_id):
        flash("That user is not an active member of this workspace.", "error")
        return redirect(url_for("workspaces.members", ws_id=ws_id))

    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
            (ws_id, target_user_id),
        )
        if cur.fetchone():
            flash("That user is already an admin.", "error")
            return redirect(url_for("workspaces.members", ws_id=ws_id))

        cur.execute(
            "INSERT INTO workspace_admins (workspace_id, user_id) VALUES (%s, %s)",
            (ws_id, target_user_id),
        )
    db.commit()

    flash("Admin added.", "success")
    return redirect(url_for("workspaces.members", ws_id=ws_id))


# ── POST /workspaces/<ws_id>/admins/<user_id>/remove ─────────────────────────

@workspaces_bp.route("/<int:ws_id>/admins/<int:target_user_id>/remove", methods=["POST"])
@login_required
def remove_admin(ws_id, target_user_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM workspace_admins WHERE workspace_id = %s",
            (ws_id,),
        )
        admin_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = %s AND status = 'active'",
            (ws_id,),
        )
        member_count = cur.fetchone()[0]

    if admin_count == 1 and member_count > 1:
        flash(
            "You are the only admin. Assign another admin before removing yourself.",
            "error",
        )
        return redirect(url_for("workspaces.members", ws_id=ws_id))

    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM workspace_admins WHERE workspace_id = %s AND user_id = %s",
            (ws_id, target_user_id),
        )
    db.commit()

    flash("Admin removed.", "success")
    return redirect(url_for("workspaces.members", ws_id=ws_id))


# ── GET /workspaces/<ws_id>/invitations ───────────────────────────────────────

@workspaces_bp.route("/<int:ws_id>/invitations")
@login_required
def invitations(ws_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, name FROM workspaces WHERE workspace_id = %s",
            (ws_id,),
        )
        ws_row = cur.fetchone()
        if not ws_row:
            abort(404)
        workspace = {"workspace_id": ws_row[0], "name": ws_row[1]}

        cur.execute(
            """
            SELECT wi.invitation_id,
                   u_ee.username AS invitee_username,
                   u_ee.email    AS invitee_email,
                   u_er.username AS inviter_username,
                   wi.invited_at
            FROM workspace_invitations wi
            JOIN users u_ee ON u_ee.user_id = wi.invitee_id
            JOIN users u_er ON u_er.user_id = wi.inviter_id
            WHERE wi.workspace_id = %s AND wi.status = 'pending'
            ORDER BY wi.invited_at DESC
            """,
            (ws_id,),
        )
        invitations_list = [
            {"invitation_id": r[0], "invitee_username": r[1], "invitee_email": r[2],
             "inviter_username": r[3], "invited_at": r[4]}
            for r in cur.fetchall()
        ]

    return render_template(
        "workspaces/invitations.html",
        workspace=workspace,
        invitations=invitations_list,
    )


# ── POST /workspaces/<ws_id>/invitations/<inv_id>/revoke ──────────────────────

@workspaces_bp.route("/<int:ws_id>/invitations/<int:inv_id>/revoke", methods=["POST"])
@login_required
def revoke_invitation(ws_id, inv_id):
    user_id = session["user_id"]
    db = get_db()

    if not _is_admin(db, ws_id, user_id):
        abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT workspace_id, status FROM workspace_invitations WHERE invitation_id = %s",
            (inv_id,),
        )
        inv = cur.fetchone()

        if not inv or inv[0] != ws_id:
            abort(404)

        if inv[1] != "pending":
            flash("Only pending invitations can be revoked.", "error")
            return redirect(url_for("workspaces.invitations", ws_id=ws_id))

        cur.execute(
            "DELETE FROM workspace_invitations WHERE invitation_id = %s",
            (inv_id,),
        )
    db.commit()

    flash("Invitation revoked.", "success")
    return redirect(url_for("workspaces.invitations", ws_id=ws_id))
