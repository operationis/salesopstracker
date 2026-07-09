"""
Access control for the SalesOps Ticket portal.

- Allow-list of users with a role: 'edit' (can tag/change) or 'view' (read-only).
- Bootstrap ADMINS always have full access + can manage others.
- Sign-in is by one-time email link (magic link) to a @bayut.sa address.
- Non-members land on a Request-Access page; the request emails the admins, who
  approve as View or Edit from a signed link.

State: access.json  ·  signing secret: secret.key
Set BASE_URL to the portal's published URL so emailed links are clickable.
"""
import configparser
import json
import os
import secrets
import smtplib
import threading
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "email_config.ini")
ACCESS = os.path.join(HERE, "access.json")
SECRET_FILE = os.path.join(HERE, "secret.key")

DOMAIN = "bayut.sa"
ADMINS = ["waheed.rasool@bayut.sa"]          # bootstrap admins (always full access)
# Where the portal is reachable — MUST match the published URL for emailed links.
BASE_URL = os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:5004")

LOGIN_MAX_AGE = 900          # sign-in link valid 15 min
APPROVE_MAX_AGE = 7 * 86400  # approval link valid 7 days
_LOCK = threading.Lock()


# --------------------------------------------------------------- secret / signer
def _secret():
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE, encoding="utf-8").read().strip()
    s = secrets.token_hex(32)
    with open(SECRET_FILE, "w", encoding="utf-8") as fh:
        fh.write(s)
    return s


_serializer = URLSafeTimedSerializer(_secret(), salt="salesops-portal")


def _dumps(obj):
    return _serializer.dumps(obj)


def _loads(token, max_age):
    try:
        return _serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def make_login_token(email):
    return _dumps({"act": "login", "email": email.lower()})


def verify_login_token(token):
    d = _loads(token, LOGIN_MAX_AGE)
    return d["email"] if d and d.get("act") == "login" else None


def make_approve_token(email, role):
    return _dumps({"act": "approve", "email": email.lower(), "role": role})


def verify_approve_token(token):
    d = _loads(token, APPROVE_MAX_AGE)
    if d and d.get("act") == "approve" and d.get("role") in ("view", "edit"):
        return d["email"], d["role"]
    return None, None


# --------------------------------------------------------------- access store
def _load():
    if os.path.exists(ACCESS):
        try:
            return json.load(open(ACCESS, encoding="utf-8"))
        except Exception:
            pass
    return {"users": {}, "requests": {}}


def _save(data):
    with _LOCK:
        with open(ACCESS, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)


def valid_domain(email):
    return (email or "").lower().strip().endswith("@" + DOMAIN)


def role_of(email):
    email = (email or "").lower().strip()
    if email in [a.lower() for a in ADMINS]:
        return "admin"
    return _load()["users"].get(email, {}).get("role")


def is_admin(email): return role_of(email) == "admin"
def can_edit(email): return role_of(email) in ("admin", "edit")
def can_view(email): return role_of(email) in ("admin", "edit", "view")


def grant(email, role, by="admin"):
    email = email.lower().strip()
    d = _load()
    d["users"][email] = {"role": role, "granted_by": by,
                         "granted_at": datetime.now(timezone.utc).isoformat()}
    d["requests"].pop(email, None)
    _save(d)


def revoke(email):
    d = _load(); d["users"].pop(email.lower().strip(), None); _save(d)


def add_request(email, note=""):
    email = email.lower().strip()
    d = _load()
    d["requests"][email] = {"requested_at": datetime.now(timezone.utc).isoformat(), "note": note}
    _save(d)


def deny_request(email):
    d = _load(); d["requests"].pop(email.lower().strip(), None); _save(d)


def list_users():
    d = _load()
    out = [{"email": a.lower(), "role": "admin", "granted_by": "bootstrap"} for a in ADMINS]
    for e, v in d["users"].items():
        if e not in [a.lower() for a in ADMINS]:
            out.append({"email": e, "role": v.get("role"), "granted_by": v.get("granted_by", ""),
                        "granted_at": v.get("granted_at", "")})
    return out


def list_requests():
    d = _load()
    return [{"email": e, **v} for e, v in d["requests"].items()]


# --------------------------------------------------------------- email
def _smtp():
    cp = configparser.ConfigParser(); cp.read(CFG)
    s = cp["smtp"]
    pw = s.get("password", "")
    if "gmail" in s.get("host", "").lower():
        pw = pw.replace(" ", "")
    return {"host": s.get("host"), "port": int(s.get("port", "587")),
            "user": s.get("username", ""), "pw": pw, "from": s.get("from_addr"),
            "tls": s.get("use_tls", "true").lower() in ("1", "true", "yes")}


def send_mail(to, subject, html):
    c = _smtp()
    to_list = to if isinstance(to, (list, tuple)) else [to]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject; msg["From"] = c["from"]; msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(html, "html"))
    srv = smtplib.SMTP(c["host"], c["port"], timeout=30)
    try:
        if c["tls"]:
            srv.starttls()
        if c["user"]:
            srv.login(c["user"], c["pw"])
        srv.sendmail(c["from"], to_list, msg.as_string())
    finally:
        srv.quit()


def _wrap(title, body):
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;color:#132a1f;max-width:560px'>"
            f"<div style='background:linear-gradient(135deg,#063d24,#0d7a3f);color:#fff;padding:14px 18px;border-radius:10px'>"
            f"<b style='font-size:15px'>SalesOps Ticket Portal</b><div style='font-size:12px;opacity:.85'>{title}</div></div>"
            f"<div style='padding:16px 4px;font-size:14px;line-height:1.5'>{body}</div>"
            f"<div style='font-size:11px;color:#5d7168;margin-top:10px'>Bayut KSA Operations - IS · automated message</div></div>")


def send_login_link(email):
    token = make_login_token(email)
    url = f"{BASE_URL}/auth?token={token}"
    html = _wrap("Sign-in link", f"Click to sign in to the SalesOps Ticket portal:<br><br>"
                 f"<a href='{url}' style='background:#0d7a3f;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700'>Sign in</a>"
                 f"<br><br><span style='font-size:12px;color:#5d7168'>This link expires in 15 minutes. If you didn't request it, ignore this email.</span>")
    send_mail(email, "Your SalesOps portal sign-in link", html)


def send_access_request(email, note=""):
    add_request(email, note)
    view_url = f"{BASE_URL}/admin/approve?token={make_approve_token(email, 'view')}"
    edit_url = f"{BASE_URL}/admin/approve?token={make_approve_token(email, 'edit')}"
    body = (f"<b>{email}</b> is requesting access to the SalesOps Ticket portal."
            + (f"<br><br><i>Note:</i> {note}" if note else "")
            + "<br><br>Grant access:<br><br>"
            f"<a href='{view_url}' style='background:#2563eb;color:#fff;padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:700;margin-right:8px'>Approve · View</a>"
            f"<a href='{edit_url}' style='background:#0d7a3f;color:#fff;padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:700'>Approve · Edit</a>"
            f"<br><br><span style='font-size:12px;color:#5d7168'>Or manage all access at <a href='{BASE_URL}/admin'>{BASE_URL}/admin</a>. Links expire in 7 days.</span>")
    send_mail(ADMINS, f"[Access request] {email} — SalesOps portal", _wrap("Access request", body))


def notify_granted(email, role):
    html = _wrap("Access granted",
                 f"You've been granted <b>{role.upper()}</b> access to the SalesOps Ticket portal.<br><br>"
                 f"<a href='{BASE_URL}/login' style='background:#0d7a3f;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700'>Sign in</a>")
    try:
        send_mail(email, "You've been granted access — SalesOps portal", html)
    except Exception:
        pass
