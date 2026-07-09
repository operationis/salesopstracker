# SalesOps Ticket Tracker

A lightweight ticketing & response-tracking portal for a shared **support inbox /
distribution group** (built for `salesops@bayut.sa`). Every email sent to the group
becomes a **ticket**; the portal shows whether the team has responded, how long each
open ticket has been waiting (live), and the first-response time — with tagging,
per-thread previews, access control, and an audit log.

> Built for **Bayut KSA Operations - IS**.

## Features
- **Tickets from a group inbox** — reads emails addressed to the group and threads them.
- **Open vs Responded** — a ticket is *Responded* once a listed team member replies;
  otherwise *Open* with a **live time-lapsed clock** (SLA-coloured). Responded tickets
  show the **response time**.
- **Ticket IDs** — stable `SO-#####` per thread.
- **Tags & filters** — `Developer / SPA / RC / Refund / FYI`. Bulk-tag via checkboxes.
  **FYI** tickets are excluded from the Open count and from response-time.
- **Thread preview + response timeline** — click a subject to see the latest email and
  the who/when/summary of each reply in the thread.
- **Access control** — allow-listed users with **View** (read-only) or **Edit** roles.
  Non-members can **request access**; admins approve **View/Edit** from an email link or
  the in-app Admin page.
- **Activity log** — every tagging/admin action recorded with person, time, and detail.
- **Sortable columns**, search by subject/sender, auto-refresh, live clocks.

## Two ways to run

### 1) Python / Flask (this repo root)
Reads the mailbox over **Gmail IMAP** (a group-member's app password) and gates access
with **one-time email sign-in links**. Runs anywhere Python runs.

```bash
pip install -r requirements.txt
cp email_config.ini.example email_config.ini    # fill in mailbox + app password
export PORTAL_BASE_URL="http://localhost:5004"    # the URL users open
python wsgi.py                                    # -> http://localhost:5004
```
Production: `./start.sh` (gunicorn) / `run_local.bat` (waitress, Windows) / `docker build . && docker run`.
Full details in **[DEPLOY.md](DEPLOY.md)**.

### 2) Google Apps Script (`apps-script/`)
A serverless variant that reads Gmail **natively** (no IMAP/app-password), uses **Google
domain sign-in** for identity/roles, and is hosted by Google. Best if you're on Google
Workspace. Setup in **[apps-script/README.md](apps-script/README.md)**.

## Configuration
Edit the constants at the top of `ticket_store.py` (Flask) or `Code.gs` (Apps Script):
- `GROUP` — the group/inbox address to track.
- `RESPONDERS` — members whose reply marks a ticket *Responded*.
- `ADMINS` — who receives access requests and can manage access.
- `WINDOW_DAYS` — how far back to scan.

## Architecture
```
Flask:  wsgi.py → tickets_app.py (routes + auth gate) → ticket_store.py (IMAP scan, tags, IDs)
                                                       → auth.py (roles, email links, approvals)
        templates/  tickets.html · login.html · request_access.html · admin.html
GAS:    apps-script/Code.gs (Gmail scan + Sheet store) · Index.html (UI)
```

## Security notes
- Secrets and runtime state are **git-ignored** (`email_config.ini`, `secret.key`,
  `access.json`, cache/tag/id/activity files). Never commit them.
- Set `PORTAL_BASE_URL` to the real published URL so emailed sign-in/approval links work.
- Run a **single worker** (in-process cache + one IMAP session); scale with threads.

## License
Internal use — see [LICENSE](LICENSE).
