from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from db import get_db
from utils import login_required

invitations_bp = Blueprint("invitations", __name__)


# ── GET /invitations ──────────────────────────────────────────────────────────

@invitations_bp.route("/invitations")
@login_required
def list_invitations():
    user_id = session["user_id"]
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT wi.invitation_id, wi.invited_at,
                   w.workspace_id, w.name AS workspace_name, w.description,
                   u.username AS inviter_username
            FROM workspace_invitations wi
            JOIN workspaces w ON wi.workspace_id = w.workspace_id
            JOIN users u ON wi.inviter_id = u.user_id
            WHERE wi.invitee_id = %s AND wi.status = 'pending'
            ORDER BY wi.invited_at DESC
            """,
            (user_id,),
        )
        workspace_invitations = [
            {
                "invitation_id": r[0], "invited_at": r[1],
                "workspace_id": r[2], "workspace_name": r[3],
                "description": r[4], "inviter_username": r[5],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT ci.invitation_id, ci.invited_at,
                   c.channel_id, c.name AS channel_name, c.channel_type,
                   w.workspace_id, w.name AS workspace_name,
                   u.username AS inviter_username
            FROM channel_invitations ci
            JOIN channels c ON ci.channel_id = c.channel_id
            JOIN workspaces w ON c.workspace_id = w.workspace_id
            JOIN users u ON ci.inviter_id = u.user_id
            WHERE ci.invitee_id = %s AND ci.status = 'pending'
            ORDER BY ci.invited_at DESC
            """,
            (user_id,),
        )
        channel_invitations = [
            {
                "invitation_id": r[0], "invited_at": r[1],
                "channel_id": r[2], "channel_name": r[3], "channel_type": r[4],
                "workspace_id": r[5], "workspace_name": r[6],
                "inviter_username": r[7],
            }
            for r in cur.fetchall()
        ]

    return render_template(
        "invitations/inbox.html",
        workspace_invitations=workspace_invitations,
        channel_invitations=channel_invitations,
    )


# ── POST /invitations/workspace/<inv_id>/accept ───────────────────────────────

@invitations_bp.route("/invitations/workspace/<int:inv_id>/accept", methods=["POST"])
@login_required
def accept_workspace_invitation(inv_id):
    user_id = session["user_id"]
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            """SELECT invitation_id, workspace_id, status
               FROM workspace_invitations
               WHERE invitation_id = %s AND invitee_id = %s""",
            (inv_id, user_id),
        )
        inv = cur.fetchone()

    if not inv:
        abort(403)

    if inv[2] != "pending":
        flash("This invitation is no longer active.", "error")
        return redirect(url_for("invitations.list_invitations"))

    workspace_id = inv[1]

    # Fetch workspace name for the flash message
    with db.cursor() as cur:
        cur.execute("SELECT name FROM workspaces WHERE workspace_id = %s", (workspace_id,))
        ws = cur.fetchone()
        workspace_name = ws[0] if ws else "workspace"

    try:
        with db.cursor() as cur:
            cur.execute(
                """UPDATE workspace_invitations SET status = 'accepted'
                   WHERE invitation_id = %s AND invitee_id = %s""",
                (inv_id, user_id),
            )
            cur.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, status, joined_at)
                   VALUES (%s, %s, 'active', NOW())
                   ON CONFLICT (workspace_id, user_id)
                   DO UPDATE SET status = 'active', joined_at = NOW()""",
                (workspace_id, user_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    flash(f"You have joined {workspace_name}.", "success")
    return redirect(url_for("workspaces.workspace_detail", ws_id=workspace_id))


# ── POST /invitations/workspace/<inv_id>/decline ──────────────────────────────

@invitations_bp.route("/invitations/workspace/<int:inv_id>/decline", methods=["POST"])
@login_required
def decline_workspace_invitation(inv_id):
    user_id = session["user_id"]
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            """SELECT invitation_id, status
               FROM workspace_invitations
               WHERE invitation_id = %s AND invitee_id = %s""",
            (inv_id, user_id),
        )
        inv = cur.fetchone()

    if not inv:
        abort(403)

    if inv[1] != "pending":
        flash("This invitation is no longer active.", "error")
        return redirect(url_for("invitations.list_invitations"))

    with db.cursor() as cur:
        cur.execute(
            """UPDATE workspace_invitations SET status = 'declined'
               WHERE invitation_id = %s AND invitee_id = %s""",
            (inv_id, user_id),
        )
    db.commit()

    flash("Invitation declined.", "info")
    return redirect(url_for("invitations.list_invitations"))


# ── POST /invitations/channel/<inv_id>/accept ─────────────────────────────────

@invitations_bp.route("/invitations/channel/<int:inv_id>/accept", methods=["POST"])
@login_required
def accept_channel_invitation(inv_id):
    user_id = session["user_id"]
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            """SELECT ci.invitation_id, ci.channel_id, ci.status,
                      c.workspace_id, c.channel_type, c.name
               FROM channel_invitations ci
               JOIN channels c ON ci.channel_id = c.channel_id
               WHERE ci.invitation_id = %s AND ci.invitee_id = %s""",
            (inv_id, user_id),
        )
        inv = cur.fetchone()

    if not inv:
        abort(403)

    channel_id   = inv[1]
    status       = inv[2]
    workspace_id = inv[3]
    channel_type = inv[4]
    channel_name = inv[5]

    if status != "pending":
        flash("This invitation is no longer active.", "error")
        return redirect(url_for("invitations.list_invitations"))

    if channel_type != "private":
        abort(403)

    # Must be an active workspace member before joining the channel
    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (workspace_id, user_id),
        )
        if not cur.fetchone():
            flash(
                "You must be an active member of the workspace before joining this channel.",
                "error",
            )
            return redirect(url_for("invitations.list_invitations"))

    try:
        with db.cursor() as cur:
            cur.execute(
                """UPDATE channel_invitations SET status = 'accepted'
                   WHERE invitation_id = %s AND invitee_id = %s""",
                (inv_id, user_id),
            )
            cur.execute(
                """INSERT INTO channel_members (channel_id, workspace_id, user_id, joined_at)
                   VALUES (%s, %s, %s, NOW())""",
                (channel_id, workspace_id, user_id),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    flash(f"You have joined #{channel_name}.", "success")
    return redirect(url_for("channels.channel_detail", ws_id=workspace_id, ch_id=channel_id))


# ── POST /invitations/channel/<inv_id>/decline ────────────────────────────────

@invitations_bp.route("/invitations/channel/<int:inv_id>/decline", methods=["POST"])
@login_required
def decline_channel_invitation(inv_id):
    user_id = session["user_id"]
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            """SELECT invitation_id, status
               FROM channel_invitations
               WHERE invitation_id = %s AND invitee_id = %s""",
            (inv_id, user_id),
        )
        inv = cur.fetchone()

    if not inv:
        abort(403)

    if inv[1] != "pending":
        flash("This invitation is no longer active.", "error")
        return redirect(url_for("invitations.list_invitations"))

    with db.cursor() as cur:
        cur.execute(
            """UPDATE channel_invitations SET status = 'declined'
               WHERE invitation_id = %s AND invitee_id = %s""",
            (inv_id, user_id),
        )
    db.commit()

    flash("Invitation declined.", "info")
    return redirect(url_for("invitations.list_invitations"))
