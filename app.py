import os

from app import create_app

app = create_app()


def _get_run_port():
    env_port = os.environ.get("PALAYKITA_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            return 5000

    try:
        from app.utils import get_settings
        from app.server_control import normalize_port

        with app.app_context():
            return normalize_port(get_settings().server_port)
    except Exception:
        return 5000


if __name__ == "__main__":
    # Debug mode is OFF by default: with debug=True Werkzeug exposes an interactive
    # traceback/console to every device on the LAN (host 0.0.0.0). Set PALAYKITA_DEBUG=1
    # only for local development.
    debug_mode = os.environ.get("PALAYKITA_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    port = _get_run_port()

    if debug_mode:
        # Werkzeug's reloader/debugger is only for local development.
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
    else:
        # Production-grade WSGI server for LAN/tablet access.
        from waitress import serve
        print(f"PalayKita is running (Waitress) at http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)


