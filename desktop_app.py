"""
desktop_app.py - PalayKita Desktop Launcher

Desktop mode opens PalayKita inside a native desktop window.

How it works:
- The desktop window uses a private local server at http://127.0.0.1:5050.
- In Settings, admins can start/stop the Wi-Fi sharing server at http://YOUR-IP:5000.
- Phones on the same Wi-Fi should use the Wi-Fi URL shown in Settings.

Run:
    python desktop_app.py
"""

import socket
import threading
import time
import webbrowser

from waitress import create_server

from app import create_app
from app.server_control import DESKTOP_HOST, DESKTOP_PORT

APP_URL = f"http://{DESKTOP_HOST}:{DESKTOP_PORT}"


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _run_desktop_server():
    flask_app = create_app()
    server = create_server(flask_app, host=DESKTOP_HOST, port=DESKTOP_PORT)
    server.run()


def main():
    if not _port_is_open(DESKTOP_HOST, DESKTOP_PORT):
        server_thread = threading.Thread(target=_run_desktop_server, daemon=True)
        server_thread.start()

        for _ in range(50):
            if _port_is_open(DESKTOP_HOST, DESKTOP_PORT):
                break
            time.sleep(0.2)

    try:
        import webview

        webview.create_window(
            title="PalayKita - Rice Milling Profit Tracker",
            url=APP_URL,
            width=1180,
            height=760,
            min_size=(390, 640),
            confirm_close=True,
        )
        webview.start(debug=False)
    except Exception:
        webbrowser.open(APP_URL)
        print(f"PalayKita Desktop is running at {APP_URL}")
        print("Open Settings > Server Control to start Wi-Fi phone access.")
        print("Close this terminal window to close desktop mode.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("PalayKita closed.")


if __name__ == "__main__":
    main()
