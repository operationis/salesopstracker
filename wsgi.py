"""
WSGI entry point for the SalesOps Ticket Tracker (port 5004).

Binds immediately and starts the background mailbox poller.

    gunicorn -w 1 -k gthread --threads 8 -b 0.0.0.0:5004 wsgi:application   # Linux
    waitress-serve --listen=0.0.0.0:5004 --threads=8 wsgi:application        # Windows

Run a SINGLE worker (in-process cache + one IMAP session); scale with threads.
"""
from tickets_app import app, start_poller

start_poller()
application = app

if __name__ == "__main__":
    import os
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5004"))
    try:
        from waitress import serve
        print(f"[tickets] waitress serving on {host}:{port}")
        serve(application, host=host, port=port, threads=8)
    except ImportError:
        application.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
