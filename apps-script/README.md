# SalesOps Ticket Tracker — Google Apps Script edition

A Google-hosted version of the SalesOps Ticket Tracker. It reads the
**salesops@bayut.sa** group's mail natively via Gmail, uses **Google sign-in**
(restricted to bayut.sa) for View/Edit access, and needs **no server, no IMAP
app-password, and no watchdog**.

## Files
| File | What |
|------|------|
| `Code.gs` | server logic — Gmail scan → tickets, access control, tagging, request/approve, timeline, activity |
| `Index.html` | the portal UI (calls the server via `google.script.run`) |
| `appsscript.json` | manifest — OAuth scopes + web-app settings |

Data is kept in a **Google Sheet** the script auto-creates on first run
("SalesOps Ticket Tracker — Data": tabs Access / Requests / Tags / TicketIDs /
Activity). The ticket list is cached (CacheService).

## Deploy (script.google.com)

1. **Who deploys matters:** sign in as an account that is a **member of the
   salesops@bayut.sa group** (so Gmail sees the group's mail) and is your admin —
   e.g. **waheed.rasool@bayut.sa**. This account is the bootstrap admin.
2. Go to **script.google.com → New project**.
3. **Project Settings** (gear) → tick **"Show appsscript.json manifest file in editor."**
4. Create the files and paste contents:
   - `Code.gs` ← paste `Code.gs`
   - **+ → HTML** named `Index` ← paste `Index.html`
   - `appsscript.json` ← replace with the one here.
5. (Optional) edit the config block at the top of `Code.gs`: `GROUP`, `WINDOW_DAYS`,
   `ADMINS`, and the `RESPONDERS` map (members whose reply marks a ticket responded).
6. **Deploy → New deployment → type: Web app**
   - **Description:** SalesOps Ticket Tracker
   - **Execute as:** **Me** (the group-member/admin account)
   - **Who has access:** **Bayut** *(your Workspace domain — "Anyone within bayut.sa")*
   - Click **Deploy**, then **Authorize access** and accept the scopes (Gmail read,
     send email, Sheets).
7. Copy the **Web app URL** — that's the portal. Share it with the team.

> The domain-restricted setting is what makes sign-in + access control work:
> Google logs each person in, and `Session.getActiveUser()` gives the portal their
> email to check View/Edit. (If you set access to "Anyone," identity won't resolve.)

## First-run
- Open the URL as the admin → you have full access. Click **Admin** to pre-add the
  Sales Ops members as **View** or **Edit**, or let them open the URL and hit
  **Request access** — you'll get an email with **Approve · View / Approve · Edit**
  buttons (and can also manage everyone from the Admin panel).

## Keep it fast (optional but recommended)
Add a trigger so the ticket cache stays warm (otherwise the first open after the
cache expires does a live Gmail scan and can take ~30–60 s):
- **Triggers** (clock icon) → **Add trigger** → function **`scheduledRefresh`**,
  event source **Time-driven**, **Minutes timer → every 30 minutes**.

## Roles
- **Edit** — can tag / bulk-move / clear tags. **View** — read-only (tickets,
  preview, timeline, activity). Admins (in `ADMINS`) have full access + manage.

## Notes / limits
- Runs as the deploying account → Gmail read + outbound mail use that mailbox
  (Workspace send limit ~1,500/day — far more than this needs).
- Scan window defaults to 90 days, capped at 400 threads (`MAX_THREADS`).
- Everything is Google-hosted; there's nothing to keep running on your machine —
  you can retire the Python 5004 app once this is live (they can also coexist; the
  data stores are separate).
- To update later: edit the files in the Apps Script editor and **Deploy → Manage
  deployments → Edit → New version**.
