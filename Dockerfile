# SalesOps Ticket Tracker — container image (port 5004)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5004 \
    PORTAL_BASE_URL=http://localhost:5004

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5004

# Single worker: in-process background poller + one IMAP session + in-memory cache.
# Scale with threads, not processes.
# NOTE: mount a volume so state persists across restarts/redeploys, and provide the
# secret config, e.g.:
#   docker run -d -p 5004:5004 \
#     -e PORTAL_BASE_URL=https://tickets.bayut.sa \
#     -v salesops_data:/app \
#     -v /secure/email_config.ini:/app/email_config.ini:ro \
#     salesops-tickets
CMD ["sh", "-c", "gunicorn -w 1 -k gthread --threads 8 --timeout 120 -b 0.0.0.0:${PORT} wsgi:application"]
