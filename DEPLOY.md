# SalesOps Ticket Tracker — Deployment

Self-contained deployment bundle for the **SalesOps Ticket Tracker** (port **5004**):
a ticketing/tracking portal over emails sent to the **salesops@bayut.sa** group, with
sign-in, View/Edit roles, request→approve access, tagging, and a response timeline.

## What's in here
| File | Purpose |
|------|---------|
| `tickets_app.py` | Flask app + routes + auth gate |
| `ticket_store.py` | IMAP poll of a group-member inbox → tickets, tags, IDs, timeline |
| `auth.py` | access list, roles, email sign-in links, request/approve flow |
| `wsgi.py` | production entry (`wsgi:application`) + background poller |
| `templates/` | `tickets.html` (portal), `login.html`, `request_access.html`, `admin.html` |
| `requirements.txt` `Procfile` `Dockerfile` `start.sh` `run_local.bat` | serving scaffolding |
| `email_config.ini.example` | template for the mail credentials (copy → `email_config.ini`) |

## How it works (important context)
`salesops@bayut.sa` is a **distribution group**, not a mailbox. The tracker polls a
**group-member's Gmail mailbox over IMAP** (default `waheed.rasool@bayut.sa`) and treats
every email whose To/Cc includes the group as a ticket. The **same account** sends the
sign-in and access-approval emails (SMTP). Both are configured in `email_config.ini`.

## Prerequisites
- Python 3.11+ (3.13 recommended).
- A group-member Gmail/Workspace account with **IMAP enabled** and a **16-char App Password**.
- Outbound SMTP (smtp.gmail.com:587) and IMAP (imap.gmail.com:993) egress.

## Configure
1. `cp email_config.ini.example email_config.ini` and fill in username / app-password / from_addr.
2. Set **`PORTAL_BASE_URL`** to the URL users will actually open (so emailed sign-in and
   approval links are clickable), e.g. `https://tickets.bayut.sa`. Defaults to `http://localhost:5004`.
3. (Optional) edit `auth.py`: `ADMINS` (who receives requests / can manage access) and
   `ticket_store.py`: `RESPONDERS` (members whose replies mark a ticket "responded").

## Run
```bash
# Local / Windows
run_local.bat                                  # waitress on :5004

# Linux / server
pip install -r requirements.txt
PORTAL_BASE_URL=https://tickets.bayut.sa ./start.sh    # gunicorn on $PORT

# Docker
docker build -t salesops-tickets .
docker run -d --name salesops-tickets -p 5004:5004 \
  -e PORTAL_BASE_URL=https://tickets.bayut.sa \
  -v salesops_data:/app \
  -v /secure/email_config.ini:/app/email_config.ini:ro \
  salesops-tickets
```

### Platform (Heroku/Render/etc.)
`Procfile` defines the `web` process. Set `PORTAL_BASE_URL` and mount/persist the state
files (below). The platform's `$PORT` is honoured.

## Operational notes
- **Run ONE worker** (`gunicorn -w 1`): the app has a single background IMAP poller +
  in-memory cache. Scale with **threads**, not processes.
- **First hit is gated** → users land on `/login`, enter their `@bayut.sa` email, and get a
  one-time sign-in link. `/healthz` is public for load-balancer checks.
- **Bootstrap admin** = the first entry in `auth.ADMINS` (waheed.rasool@bayut.sa). Admins
  manage access at `/admin`.

## Persistent state (MUST survive restarts/redeploys)
These files are created at runtime in the app dir — keep them on a **persistent volume**
(the Docker example mounts `salesops_data:/app`). Losing them has consequences:
| File | If lost |
|------|---------|
| `secret.key` | all sessions + pending sign-in/approve links invalidated |
| `access.json` | **the entire allow-list (who can log in) is wiped** |
| `tickets_ids.json` | Ticket IDs (SO-#####) get reassigned |
| `tickets_tags.json` | tags (Developer/SPA/RC/Refund/FYI) lost |
| `activity_log.json` | activity history lost |
| `tickets_cache.json` | rebuilt automatically on next poll (safe to lose) |

## Secrets — do not commit
`email_config.ini`, `secret.key`, and `access.json` are git-ignored. Provide them
out-of-band (mounted file / platform secret), never in the image or repo.

## Updating from the live folder
This is a copy of `salesops_tickets/`. When code/UI changes upstream, re-copy:
`auth.py`, `ticket_store.py`, `tickets_app.py`, `wsgi.py`, and `templates/*.html`.
