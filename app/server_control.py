"""
app/server_control.py - Desktop Wi-Fi server controls for PalayKita.

Desktop mode uses a private local server for the desktop window, then this
module can start/stop a separate Wi-Fi server on the configured port so phones
on the same Wi-Fi can open http://YOUR-IP:PORT.
"""

from __future__ import annotations

import os
import socket
import threading
from typing import Optional, Tuple

from waitress import create_server


SHARED_HOST = "0.0.0.0"
DEFAULT_SHARED_PORT = 5000
DESKTOP_HOST = "127.0.0.1"
DESKTOP_PORT = 5050


def normalize_port(value=None, fallback=DEFAULT_SHARED_PORT) -> int:
    """Return a safe TCP port number for the Wi-Fi sharing server."""
    if value in (None, ""):
        if fallback is None:
            raise ValueError("Port is required.")
        value = fallback

    try:
        port = int(value)
    except (TypeError, ValueError):
        if fallback is None:
            raise ValueError("Port must be a number.")
        port = int(fallback)

    if port < 1024 or port > 65535:
        raise ValueError("Port must be between 1024 and 65535.")
    if port == DESKTOP_PORT:
        raise ValueError(f"Port {DESKTOP_PORT} is reserved for the desktop window. Choose another port.")
    return port


def get_configured_shared_port() -> int:
    """Read the saved port from settings; env PALAYKITA_PORT can override it."""
    env_port = os.environ.get("PALAYKITA_PORT")
    if env_port:
        try:
            return normalize_port(env_port)
        except ValueError:
            pass

    try:
        from app.utils import get_settings

        settings = get_settings()
        return normalize_port(getattr(settings, "server_port", DEFAULT_SHARED_PORT), DEFAULT_SHARED_PORT)
    except Exception:
        return DEFAULT_SHARED_PORT


def get_lan_ip() -> str:
    """Return the best local network IP address for phone access."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def port_can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


class SharedServerManager:
    def __init__(self):
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._port: Optional[int] = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server is not None)

    def current_port(self) -> Optional[int]:
        return self._port if self.is_running() else None

    def start(self, port=None) -> Tuple[bool, str]:
        with self._lock:
            if self.is_running():
                return True, f"Wi-Fi server is already running on port {self._port}."

            try:
                selected_port = normalize_port(port if port is not None else get_configured_shared_port())
            except ValueError as exc:
                return False, str(exc)

            if not port_can_bind(SHARED_HOST, selected_port):
                ip = get_lan_ip()
                return False, (
                    f"Port {selected_port} is already in use. Choose another port in Settings, "
                    f"or open the active server at http://{ip}:{selected_port}."
                )

            from app import create_app

            flask_app = create_app()
            self._server = create_server(flask_app, host=SHARED_HOST, port=selected_port)
            self._thread = threading.Thread(target=self._server.run, daemon=True)
            self._port = selected_port
            self._thread.start()

            return True, f"Wi-Fi server started. Phone access: http://{get_lan_ip()}:{selected_port}"

    def stop(self) -> Tuple[bool, str]:
        with self._lock:
            if not self.is_running():
                return False, "Wi-Fi server is not running from desktop mode."

            server = self._server
            thread = self._thread
            stopped_port = self._port
            self._server = None
            self._thread = None
            self._port = None

            try:
                server.close()
                if thread:
                    thread.join(timeout=3)
            except Exception as exc:
                return False, f"Unable to stop Wi-Fi server: {exc}"

            return True, f"Wi-Fi server on port {stopped_port} stopped. Desktop app is still running."


shared_server_manager = SharedServerManager()


def get_server_status() -> dict:
    ip = get_lan_ip()
    configured_port = get_configured_shared_port()
    manager_running = shared_server_manager.is_running()
    active_port = shared_server_manager.current_port() or configured_port
    port_active = port_is_open("127.0.0.1", active_port)

    if manager_running:
        status_label = "Running"
        status_detail = f"Started from PalayKita Desktop settings on port {active_port}."
        can_start = False
        can_stop = True
    elif port_active:
        status_label = "Running"
        status_detail = f"Port {active_port} is active. This is likely web mode or another PalayKita server."
        can_start = False
        can_stop = False
    else:
        status_label = "Stopped"
        status_detail = "Wi-Fi sharing server is not running. Desktop app remains available on this computer."
        can_start = True
        can_stop = False

    return {
        "status_label": status_label,
        "status_detail": status_detail,
        "is_running": manager_running or port_active,
        "managed_by_desktop": manager_running,
        "port_active": port_active,
        "can_start": can_start,
        "can_stop": can_stop,
        "ip": ip,
        "port": active_port,
        "configured_port": configured_port,
        "wifi_url": f"http://{ip}:{active_port}",
        "desktop_url": f"http://{DESKTOP_HOST}:{DESKTOP_PORT}",
        "desktop_port": DESKTOP_PORT,
    }
