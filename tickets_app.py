"""
SalesOps Ticket Tracker — Flask portal (port 5004) with access control.

Access: allow-listed @bayut.sa users with role 'view' (read-only) or 'edit'
(can tag/change). Sign-in via one-time email link. Non-members can request
access; admins approve as View/Edit from an emailed link or the /admin page.
"""
import json
import threading
import time
import traceback

from flask import (Flask, render_template, render_template_string, request,
                   session, redirect, abort)

import ticket_store
import auth

app = Flask(__name__)
app.secret_key = auth._secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=7 * 86400)
POLL_INTERVAL = 300

PUBLIC = {"login", "auth_verify", "logout", "request_access", "admin_approve", "healthz", "static"}


def _json(o):
    return app.response_class(json.dumps(o), mimetype="application/json")


def _user():
    return session.get("user")


@app.before_request
def _gate():
    ep = request.endpoint
    if ep in PUBLIC:
        return
    u = _user()
    if not u:
        return redirect("/login")
    if ep and ep.startswith("admin") and not auth.is_admin(u):
        abort(403)
    if not auth.can_view(u):
        return redirect("/request-access")


# ----------------------------------------------------------------- auth pages
@app.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not auth.valid_domain(email):
            msg = "Please use your @bayut.sa email."
        elif auth.can_view(email):
            try:
                auth.send_login_link(email); msg = "✓ Sign-in link sent — check your inbox."
            except Exception:
                traceback.print_exc(); msg = "Could not send the email; try again shortly."
        else:
            return redirect("/request-access?email=" + email)
    return render_template("login.html", msg=msg)


@app.route("/auth")
def auth_verify():
    email = auth.verify_login_token(request.args.get("token", ""))
    if not email:
        return render_template("login.html", msg="That sign-in link is invalid or expired. Request a new one.")
    session["user"] = email
    session.permanent = True
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/request-access", methods=["GET", "POST"])
def request_access():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        note = (request.form.get("note") or "").strip()[:400]
        if not auth.valid_domain(email):
            return render_template("request_access.html", email=email, sent=False,
                                   msg="Please use your @bayut.sa email.")
        try:
            auth.send_access_request(email, note)
        except Exception:
            traceback.print_exc()
        return render_template("request_access.html", email=email, sent=True, msg="")
    return render_template("request_access.html", email=request.args.get("email", ""), sent=False, msg="")


# ----------------------------------------------------------------- admin
@app.route("/admin/approve")
def admin_approve():
    email, role = auth.verify_approve_token(request.args.get("token", ""))
    if not email:
        return render_template_string(_CONFIRM, title="Link invalid",
                                      body="This approval link is invalid or has expired. Approve from <a href='/admin'>/admin</a> instead.")
    auth.grant(email, role, by="email-approval")
    auth.notify_granted(email, role)
    return render_template_string(_CONFIRM, title="Access granted",
                                  body=f"<b>{email}</b> now has <b>{role.upper()}</b> access. They've been emailed a sign-in link.")


@app.route("/admin")
def admin():
    return render_template("admin.html", users=auth.list_users(), requests=auth.list_requests(), me=_user())


@app.route("/admin/set-role", methods=["POST"])
def admin_set_role():
    b = request.get_json(force=True, silent=True) or {}
    email, role = (b.get("email") or "").lower(), b.get("role")
    if role in ("view", "edit") and auth.valid_domain(email):
        auth.grant(email, role, by=_user()); auth.notify_granted(email, role)
        return _json({"ok": True})
    return _json({"ok": False, "error": "bad email/role"})


@app.route("/admin/remove", methods=["POST"])
def admin_remove():
    b = request.get_json(force=True, silent=True) or {}
    auth.revoke((b.get("email") or "").lower())
    return _json({"ok": True})


@app.route("/admin/deny", methods=["POST"])
def admin_deny():
    b = request.get_json(force=True, silent=True) or {}
    auth.deny_request((b.get("email") or "").lower())
    return _json({"ok": True})


# ----------------------------------------------------------------- portal
@app.route("/")
def home():
    return render_template("tickets.html")


@app.route("/me")
def me():
    u = _user()
    return _json({"email": u, "role": auth.role_of(u), "can_edit": auth.can_edit(u), "is_admin": auth.is_admin(u)})


@app.route("/tickets")
def tickets():
    data = ticket_store.load_cache()
    if data is None:
        try:
            data = ticket_store.refresh()
        except Exception:
            traceback.print_exc()
            data = {"error": True, "tickets": [], "total": 0, "open": 0, "responded": 0,
                    "fyi": 0, "avg_response_secs": 0, "tag_list": ticket_store.TAGS}
    return _json(data)


@app.route("/thread")
def thread():
    try:
        return _json(ticket_store.get_thread(request.args.get("thrid", "")))
    except Exception:
        traceback.print_exc(); return _json({"error": "failed to load thread"})


@app.route("/tag", methods=["POST"])
def tag():
    if not auth.can_edit(_user()):
        return _json({"ok": False, "error": "view-only: you don't have edit access"}), 403
    body = request.get_json(force=True, silent=True) or {}
    thrids = body.get("thrids") or []
    if not thrids:
        return _json({"ok": False, "error": "no tickets selected"})
    ticket_store.set_tags(thrids, add=body.get("add") or [], remove=body.get("remove") or [],
                          replace=body.get("replace", None), user=_user())
    d = ticket_store.refresh()
    return _json({"ok": True, "open": d["open"], "responded": d["responded"], "fyi": d["fyi"]})


@app.route("/activity")
def activity():
    return _json({"log": ticket_store.load_activity(limit=int(request.args.get("limit", 500)))})


@app.route("/refresh")
def refresh():
    if not auth.can_edit(_user()):
        return _json({"ok": False, "error": "view-only"}), 403
    try:
        d = ticket_store.refresh(); return _json({"ok": True, "total": d["total"]})
    except Exception:
        return (traceback.format_exc(), 500)


@app.route("/healthz")
def healthz():
    return ("ok", 200)


_CONFIRM = """<!doctype html><meta charset=utf-8><title>{{title}}</title>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#f4f7f5;color:#132a1f;display:flex;justify-content:center;padding:60px 16px">
<div style="max-width:520px;background:#fff;border:1px solid #dce6df;border-radius:14px;padding:26px 30px">
<h2 style="color:#0d7a3f;margin:0 0 10px">{{title}}</h2><div style="font-size:15px;line-height:1.5">{{body|safe}}</div></div></body>"""


def start_poller():
    def _p():
        while True:
            try:
                ticket_store.refresh()
            except Exception:
                traceback.print_exc()
            time.sleep(POLL_INTERVAL)
    threading.Thread(target=_p, daemon=True).start()


if __name__ == "__main__":
    start_poller()
    app.run(host="127.0.0.1", port=5004, threaded=True, debug=False, use_reloader=False)
