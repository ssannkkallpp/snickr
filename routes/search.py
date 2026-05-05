import re
from markupsafe import escape
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from db import get_db
from utils import login_required

search_bp = Blueprint("search", __name__)


@search_bp.route("/search")
@login_required
def search():
    user_id = session["user_id"]

    workspace_id_raw = request.args.get("workspace", "").strip()
    q = request.args.get("q", "").strip()

    if not workspace_id_raw or not q:
        flash("Please select a workspace and enter a search term.", "error")
        return redirect(url_for("workspaces.list_workspaces"))

    try:
        workspace_id = int(workspace_id_raw)
    except ValueError:
        flash("Please select a workspace and enter a search term.", "error")
        return redirect(url_for("workspaces.list_workspaces"))

    db = get_db()

    # Verify active workspace membership — access control before any query
    with db.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id = %s AND user_id = %s AND status = 'active'""",
            (workspace_id, user_id),
        )
        if not cur.fetchone():
            abort(403)

    with db.cursor() as cur:
        cur.execute(
            "SELECT name FROM workspaces WHERE workspace_id = %s",
            (workspace_id,),
        )
        ws = cur.fetchone()
        if not ws:
            abort(404)
        workspace_name = ws[0]

    # Fetch all active workspaces for the session user (workspace selector)
    with db.cursor() as cur:
        cur.execute(
            """SELECT w.workspace_id, w.name
               FROM workspaces w
               JOIN workspace_members wm ON wm.workspace_id = w.workspace_id
               WHERE wm.user_id = %s AND wm.status = 'active'
               ORDER BY w.name""",
            (user_id,),
        )
        user_workspaces = [{"workspace_id": r[0], "name": r[1]} for r in cur.fetchall()]

    # Query 7 — full-text search restricted to channels the session user belongs to
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.message_id,
                m.body,
                m.posted_at,
                u.username AS posted_by,
                u.nickname,
                c.channel_id,
                c.name      AS channel_name,
                c.channel_type
            FROM messages m
            JOIN channels c        ON m.channel_id = c.channel_id
            JOIN users u           ON m.user_id = u.user_id
            JOIN channel_members cm
                ON cm.channel_id = m.channel_id AND cm.user_id = %s
            WHERE c.workspace_id = %s
              AND m.body_tsv @@ plainto_tsquery('english', %s)
            ORDER BY m.posted_at ASC, m.message_id ASC
            """,
            (user_id, workspace_id, q),
        )
        rows = cur.fetchall()

    # HTML-escape body first, then wrap keyword occurrences in <mark>
    results = []
    for r in rows:
        safe_body = str(escape(r[1]))
        highlighted = re.sub(
            re.escape(q),
            lambda m: f"<mark>{m.group()}</mark>",
            safe_body,
            flags=re.IGNORECASE,
        )
        results.append({
            "message_id":      r[0],
            "highlighted_body": highlighted,
            "posted_at":       r[2],
            "posted_by":       r[3],
            "nickname":        r[4],
            "channel_id":      r[5],
            "channel_name":    r[6],
            "channel_type":    r[7],
        })

    return render_template(
        "search.html",
        results=results,
        q=q,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        user_workspaces=user_workspaces,
        result_count=len(results),
    )
