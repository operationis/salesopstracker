# SalesOps Ticket Tracker (port 5004)

A live ticketing / tracking portal for emails sent to the **salesops@bayut.sa**
distribution group. Every inbound email to the group is a **ticket**:

- **OPEN** — no reply yet from a listed team member; shows a live *time-lapsed* clock.
- **RESPONDED** — a listed member replied; shows the *response time* (first reply − received).

## How it works
`salesops@bayut.sa` is a **group** (no mailbox of its own), so the tracker polls a
**group-member inbox over Gmail IMAP** and searches Gmail's *All Mail* for messages
whose To/Cc includes the group. Messages are grouped into threads (Gmail thread id).

- **Polled inbox / credentials:** `email_config.ini` (`[smtp] username` + app `password`).
  Currently `waheed.rasool@bayut.sa`. Any group member's app password works.
- **Responders** (a reply from any of these marks a ticket RESPONDED) — edit in
  `ticket_store.py` `RESPONDERS`: Sales Ops, Faisal Javed, Aisha Naveed, Hazim Tahir,
  Ayman Saber, Fahad Dafer Alshehri, Waheed Tahir, Waheed Rasool.
- **Scope:** last `WINDOW_DAYS` (90) days. `INBOUND_ONLY=True` excludes the team's own
  alert/broadcast emails to the group (set False to track every email).

## Run
```bat
run_tickets.bat            REM  -> http://127.0.0.1:5004  (waitress)
```
or `python tickets_app.py` (Flask dev server). The mailbox is re-polled every 5 min
in the background; the page also pulls fresh data every 60s and ticks the open-ticket
clocks every second.

Routes: `/` portal · `/tickets` JSON · `/refresh` force re-poll · `/healthz`.

## Important limitation (data source)
Reading one member's inbox only sees a reply if it was **reply-all to the group** (or
authored by the polled account). A private reply straight to the requester is not
visible, so some handled tickets may still show **Open**. For fully accurate response
tracking across all members, switch the source to the **Gmail API with Workspace
domain-wide delegation** (reads the group/all members) — a heavier, admin-gated setup.

## Files
`ticket_store.py` (IMAP poll + ticket logic) · `tickets_app.py` (Flask) ·
`wsgi.py` (prod entry) · `templates/tickets.html` (portal UI) · `email_config.ini`
(secret, git-ignored) · `tickets_cache.json` (cache, git-ignored).
