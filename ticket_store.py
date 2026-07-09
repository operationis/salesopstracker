"""
SalesOps ticket store — reads a group-member's Gmail mailbox over IMAP and turns
every email addressed to the salesops@bayut.sa GROUP into a tracked ticket.

Features:
  - Stable Ticket IDs (SO-00001 ...), persisted across polls.
  - Manual tags (Developer / SPA / RC / Refund / FYI) with a persistent store.
  - FYI-tagged tickets are excluded from the Open count and from response-time.
  - Per-thread message list (uid/from/date) + on-demand body fetch for the
    subject preview and the response timeline.
  - Activity log for portal actions (tagging, etc.).
"""
import configparser
import email
import imaplib
import json
import os
import re
import threading
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "email_config.ini")
CACHE = os.path.join(HERE, "tickets_cache.json")
TAGS_FILE = os.path.join(HERE, "tickets_tags.json")     # {thrid: [tags]}
IDS_FILE = os.path.join(HERE, "tickets_ids.json")       # {thrid: "SO-00001"}
ACT_FILE = os.path.join(HERE, "activity_log.json")      # [ {ts,user,action,thrids,detail} ]

GROUP = "salesops@bayut.sa"
WINDOW_DAYS = 90
IMAP_HOST = "imap.gmail.com"
INBOUND_ONLY = True

TAGS = ["Developer", "SPA", "RC", "Refund", "FYI"]      # selectable tags
FYI_TAG = "FYI"

RESPONDERS = {
    "salesops@bayut.sa": "Sales Ops",
    "salesop@bayut.sa": "Sales Ops",
    "faisal.javed@bayut.sa": "Faisal Javed",
    "aisha.naveed@bayut.sa": "Aisha Naveed",
    "hazim.tahir@bayut.sa": "Hazim Tahir",
    "aymansaber.alsabahy@bayut.sa": "Ayman Saber",
    "fahad.dafer@bayut.sa": "Fahad Dafer Alshehri",
    "waheed.tahir@bayut.sa": "Waheed Tahir",
    "waheed.rasool@bayut.sa": "Waheed Rasool",
    "mahmoud.elsayed@bayut.sa": "Mahmoud Elsayed Elmshaikh",
    "abduljabbar.mohammed@bayut.sa": "Abdul Jabbar Mohammed",
}

_LOCK = threading.Lock()


# ------------------------------------------------------------------ helpers
def _creds():
    cp = configparser.ConfigParser(); cp.read(CFG)
    s = cp["smtp"]
    return s.get("username"), s.get("password", "").replace(" ", "")


def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _first_addr(v):
    a = getaddresses([v or ""])
    if not a:
        return "", ""
    n, addr = a[0]
    return _dec(n), (addr or "").strip().lower()


def _all_addrs(v):
    return [(a or "").strip().lower() for _, a in getaddresses([v or ""]) if a]


def _iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _strip_re(s):
    return re.sub(r"^\s*(re|fwd|fw)\s*:\s*", "", s or "", flags=re.I).strip()


def _read_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default
    return default


def _write_json(path, data):
    with _LOCK:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


# ------------------------------------------------------------------ tags / ids / activity
def load_tags():
    return _read_json(TAGS_FILE, {})


def load_ids():
    return _read_json(IDS_FILE, {})


def set_tags(thrids, add=None, remove=None, replace=None, user="unknown"):
    """Add/remove/replace tags for a list of thread ids. Persists + logs."""
    tags = load_tags()
    add = add or []; remove = remove or []
    for th in thrids:
        cur = set(tags.get(th, []))
        if replace is not None:
            cur = set(replace)
        cur |= set(add)
        cur -= set(remove)
        tags[th] = [t for t in TAGS if t in cur]   # keep canonical order
    _write_json(TAGS_FILE, tags)
    detail = (("+" + ",".join(add)) if add else "") + (("  -" + ",".join(remove)) if remove else "") \
             + (("  =" + ",".join(replace)) if replace is not None else "")
    log_activity(user, "tag", thrids, detail.strip())
    return tags


def log_activity(user, action, thrids, detail=""):
    log = _read_json(ACT_FILE, [])
    log.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user or "unknown",
        "action": action,
        "thrids": list(thrids) if not isinstance(thrids, str) else [thrids],
        "detail": detail,
    })
    _write_json(ACT_FILE, log[-5000:])   # keep last 5000 entries


def load_activity(limit=500):
    return list(reversed(_read_json(ACT_FILE, [])))[:limit]


# ------------------------------------------------------------------ IMAP fetch
def _fetch_messages():
    user, pw = _creds()
    M = imaplib.IMAP4_SSL(IMAP_HOST, 993); M.login(user, pw)
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        query = f'(to:{GROUP} OR cc:{GROUP}) newer_than:{WINDOW_DAYS}d'
        typ, data = M.uid("search", None, "X-GM-RAW", '"' + query + '"')
        uids = data[0].split() if data and data[0] else []
        out = []
        for i in range(0, len(uids), 200):
            chunk = b",".join(uids[i:i + 200])
            typ, resp = M.uid("fetch", chunk,
                              "(X-GM-THRID BODY.PEEK[HEADER.FIELDS (FROM TO CC DATE SUBJECT)])")
            for part in resp:
                if not isinstance(part, tuple):
                    continue
                meta = part[0].decode("utf-8", "ignore")
                mt = re.search(r"X-GM-THRID (\d+)", meta)
                mu = re.search(r"UID (\d+)", meta)
                if not mt:
                    continue
                hdr = email.message_from_bytes(part[1])
                try:
                    dt = parsedate_to_datetime(hdr.get("Date"))
                except Exception:
                    continue
                if dt is None:
                    continue
                fn, fa = _first_addr(hdr.get("From"))
                out.append({"thrid": mt.group(1), "uid": mu.group(1) if mu else None,
                            "from_name": fn, "from_addr": fa, "date": dt,
                            "subject": _dec(hdr.get("Subject"))})
        return out
    finally:
        try: M.logout()
        except Exception: pass


def _extract_text(msg, limit=4000):
    """Plain-text body of an email.message.Message (first text/plain part)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")[:limit]
                except Exception:
                    continue
        # fall back to stripped html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    return re.sub(r"<[^>]+>", " ", html)[:limit]
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")[:limit]
    except Exception:
        return ""


def fetch_bodies(uids):
    """uid -> {from, date, subject, body} for the given All-Mail UIDs."""
    uids = [u for u in uids if u]
    if not uids:
        return {}
    user, pw = _creds()
    M = imaplib.IMAP4_SSL(IMAP_HOST, 993); M.login(user, pw)
    out = {}
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        typ, resp = M.uid("fetch", ",".join(uids), "(UID BODY.PEEK[])")
        for part in resp:
            if not isinstance(part, tuple):
                continue
            meta = part[0].decode("utf-8", "ignore")
            mu = re.search(r"UID (\d+)", meta)
            if not mu:
                continue
            msg = email.message_from_bytes(part[1])
            fn, fa = _first_addr(msg.get("From"))
            try:
                dt = parsedate_to_datetime(msg.get("Date"))
            except Exception:
                dt = None
            out[mu.group(1)] = {
                "from_name": fn, "from_addr": fa,
                "date": _iso(dt) if dt else "",
                "subject": _dec(msg.get("Subject")),
                "body": _clean_body(_extract_text(msg)),
            }
    finally:
        try: M.logout()
        except Exception: pass
    return out


def _clean_body(t):
    t = re.sub(r"\r\n", "\n", t or "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ------------------------------------------------------------------ build
def build_tickets():
    msgs = _fetch_messages()
    threads = {}
    for m in msgs:
        threads.setdefault(m["thrid"], []).append(m)

    tags_map = load_tags()
    ids_map = load_ids()

    # assign stable Ticket IDs to any new threads, in received order (oldest first)
    order = sorted(threads.items(), key=lambda kv: min(x["date"] for x in kv[1]))
    nextnum = (max([int(v.split("-")[1]) for v in ids_map.values()], default=0) + 1) if ids_map else 1
    changed = False
    for thrid, _ in order:
        if thrid not in ids_map:
            ids_map[thrid] = f"SO-{nextnum:05d}"; nextnum += 1; changed = True
    if changed:
        _write_json(IDS_FILE, ids_map)

    tickets = []
    excluded_internal = 0
    for thrid, items in threads.items():
        items.sort(key=lambda x: x["date"])
        opener = items[0]
        if INBOUND_ONLY and opener["from_addr"] in RESPONDERS:
            excluded_internal += 1
            continue
        open_dt = opener["date"]
        responded_at, responder = None, None
        for m in items[1:]:
            if m["from_addr"] in RESPONDERS:
                responded_at = m["date"]
                responder = RESPONDERS.get(m["from_addr"], m["from_name"] or m["from_addr"])
                break
        tg = tags_map.get(thrid, [])
        fyi = FYI_TAG in tg
        msgs_out = [{"from_name": m["from_name"], "from_addr": m["from_addr"],
                     "date": _iso(m["date"]), "uid": m["uid"],
                     "is_responder": m["from_addr"] in RESPONDERS} for m in items]
        rec = {
            "thrid": thrid, "ticket_id": ids_map.get(thrid, ""),
            "subject": _strip_re(opener["subject"]) or "(no subject)",
            "requester_name": opener["from_name"] or opener["from_addr"],
            "requester_addr": opener["from_addr"],
            "received": _iso(open_dt), "messages": len(items),
            "tags": tg, "fyi": fyi, "msg_list": msgs_out,
            "latest_uid": items[-1]["uid"], "latest_date": _iso(items[-1]["date"]),
        }
        if responded_at:
            rec.update(status="responded", responder=responder,
                       responded_at=_iso(responded_at),
                       response_secs=int((responded_at - open_dt).total_seconds()))
        else:
            rec.update(status="open", responder=None, responded_at=None, response_secs=None)
        tickets.append(rec)

    tickets.sort(key=lambda t: t["received"], reverse=True)
    # FYI excluded from open count AND from response-time
    open_n = sum(1 for t in tickets if t["status"] == "open" and not t["fyi"])
    resp = [t for t in tickets if t["status"] == "responded" and not t["fyi"]]
    avg = int(sum(t["response_secs"] for t in resp) / len(resp)) if resp else 0
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "group": GROUP, "window_days": WINDOW_DAYS, "inbound_only": INBOUND_ONLY,
        "excluded_internal": excluded_internal, "tag_list": TAGS,
        "total": len(tickets), "open": open_n,
        "responded": len(resp), "fyi": sum(1 for t in tickets if t["fyi"]),
        "avg_response_secs": avg, "tickets": tickets,
    }


def get_thread(thrid):
    """Response timeline for a thread: each message with from/date + body snippet,
    plus the full body of the latest message (preview)."""
    data = load_cache()
    tk = None
    for t in (data or {}).get("tickets", []):
        if t["thrid"] == thrid:
            tk = t; break
    if not tk:
        return {"error": "ticket not found"}
    uids = [m["uid"] for m in tk["msg_list"] if m["uid"]]
    bodies = fetch_bodies(uids)
    timeline = []
    for m in tk["msg_list"]:
        b = bodies.get(m["uid"], {})
        body = b.get("body", "")
        timeline.append({
            "from_name": m["from_name"], "from_addr": m["from_addr"],
            "date": m["date"], "is_responder": m["is_responder"],
            "summary": (body[:280] + ("…" if len(body) > 280 else "")) if body else "",
        })
    latest = bodies.get(tk["latest_uid"], {})
    return {"ticket_id": tk["ticket_id"], "subject": tk["subject"],
            "requester": tk["requester_name"], "requester_addr": tk["requester_addr"],
            "tags": tk["tags"], "status": tk["status"], "timeline": timeline,
            "latest_body": latest.get("body", ""), "latest_from": latest.get("from_name", "")}


def load_cache():
    return _read_json(CACHE, None)


def refresh(save=True):
    payload = build_tickets()
    if save:
        _write_json(CACHE, payload)
    return payload


if __name__ == "__main__":
    import sys
    def _p(s): sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
    p = refresh()
    _p(f"tickets: {p['total']} | open(excl FYI): {p['open']} | responded: {p['responded']} "
       f"| fyi: {p['fyi']} | avg: {p['avg_response_secs']//60}m | excluded internal: {p['excluded_internal']}")
