"""
PalayKita Offline Activation / License Manager

Build-friendly version:
- Uses only Python standard library.
- No cryptography dependency.
- License key is locked to this computer's Computer ID.

Security note:
This is good practical copy-protection for local clients. For stronger enterprise
licensing later, use an online license server.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import platform
import socket
import uuid
from typing import Any, Dict, Optional, Tuple

from config import INSTANCE_DIR

PRODUCT_NAME = "PalayKita"
LICENSE_FILE = str(INSTANCE_DIR / "license.json")
_DEV_LICENSE_SECRET = b"palaykita-local-dev-license-secret-change-me"


def _signing_secret() -> bytes:
    secret = os.environ.get("PALAYKITA_LICENSE_SECRET", "").strip()
    if not secret:
        return _DEV_LICENSE_SECRET

    try:
        return base64.b64decode(secret.encode("ascii"), validate=True)
    except Exception:
        return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    value = "".join(str(value or "").strip().split())
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _canonical_json(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _make_signature(payload: Dict[str, Any]) -> str:
    digest = hmac.new(_signing_secret(), _canonical_json(payload), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a or ""), str(b or ""))


def _get_windows_machine_guid() -> str:
    if platform.system().lower() != "windows":
        return ""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value or "").strip()
    except Exception:
        return ""


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return platform.node()


def _mac_address() -> str:
    try:
        mac = uuid.getnode()
        return f"{mac:012X}"
    except Exception:
        return ""


def get_computer_id() -> str:
    """
    Stable public Computer ID shown to the client.
    Raw device details are hashed and never displayed.
    """
    raw_parts = [
        PRODUCT_NAME,
        platform.system(),
        platform.machine(),
        _safe_hostname(),
        _mac_address(),
        _get_windows_machine_guid(),
    ]
    raw = "|".join(str(x or "").strip().lower() for x in raw_parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:20]
    return "-".join(digest[i:i + 4] for i in range(0, len(digest), 4))


def decode_activation_key(activation_key: str) -> Dict[str, Any]:
    key = "".join(str(activation_key or "").strip().split())

    if key.upper().startswith("PALAYKITA-"):
        key = key[len("PALAYKITA-"):]

    raw = _b64url_decode(key)
    data = json.loads(raw.decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Invalid activation key format.")

    return data


def validate_license_data(license_data: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    try:
        payload = license_data.get("payload")
        signature = license_data.get("signature")

        if not isinstance(payload, dict) or not signature:
            return False, "Invalid license file format.", None

        expected_signature = _make_signature(payload)
        if not _constant_time_equal(signature, expected_signature):
            return False, "Invalid activation key signature.", payload

        if payload.get("product") != PRODUCT_NAME:
            return False, "This license is not for PalayKita.", payload

        licensed_computer_id = str(payload.get("computer_id") or "").strip().upper()
        current_computer_id = get_computer_id().upper()

        if licensed_computer_id != current_computer_id:
            return False, "This license key is for another computer.", payload

        expires_on = payload.get("expires_on")
        if expires_on:
            expiry = _dt.date.fromisoformat(str(expires_on).split("T")[0])
            today = _dt.date.today()
            if today > expiry:
                return False, f"This license expired on {expires_on}.", payload

        return True, "PalayKita is activated.", payload

    except Exception as exc:
        return False, f"Invalid license: {exc}", None


def validate_license() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not os.path.exists(LICENSE_FILE):
        return False, "PalayKita is not activated.", None

    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            license_data = json.load(f)
    except Exception as exc:
        return False, f"Cannot read license file: {exc}", None

    return validate_license_data(license_data)


def is_activated() -> bool:
    valid, _, _ = validate_license()
    return valid


def activate_from_key(activation_key: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    try:
        license_data = decode_activation_key(activation_key)
        valid, message, payload = validate_license_data(license_data)

        if not valid:
            return False, message, payload

        os.makedirs(str(INSTANCE_DIR), exist_ok=True)
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(license_data, f, indent=2, ensure_ascii=False)

        return True, "Activation successful.", payload

    except Exception as exc:
        return False, f"Activation failed: {exc}", None


def days_remaining(expires_on: Optional[str]) -> str:
    if not expires_on:
        return "Lifetime"

    try:
        expiry = _dt.date.fromisoformat(str(expires_on).split("T")[0])
        days = (expiry - _dt.date.today()).days
        if days < 0:
            return f"Expired {abs(days)} day(s) ago"
        if days == 0:
            return "Expires today"
        return f"{days} day(s)"
    except Exception:
        return "—"


def format_license_type(value: Optional[str]) -> str:
    if not value:
        return "—"
    return str(value).replace("_", " ").title()


def format_date(value: Optional[str]) -> str:
    if not value:
        return "Lifetime / No expiration"
    text = str(value)
    return text.split("T")[0] if "T" in text else text


def license_status() -> Dict[str, Any]:
    valid, message, payload = validate_license()

    status = {
        "activated": valid,
        "message": message,
        "computer_id": get_computer_id(),
        "license_file": LICENSE_FILE,
        "business_name": "—",
        "owner_name": "—",
        "license_type": "—",
        "license_type_display": "—",
        "issued_at": "—",
        "issued_at_display": "—",
        "expires_on": None,
        "expires_on_display": "Lifetime / No expiration",
        "days_remaining": "—",
    }

    if payload:
        expires = payload.get("expires_on")
        status.update({
            "business_name": payload.get("business_name") or "—",
            "owner_name": payload.get("owner_name") or "—",
            "license_type": payload.get("license_type") or "—",
            "license_type_display": format_license_type(payload.get("license_type")),
            "issued_at": payload.get("issued_at") or "—",
            "issued_at_display": format_date(payload.get("issued_at")) if payload.get("issued_at") else "—",
            "expires_on": expires,
            "expires_on_display": format_date(expires),
            "days_remaining": days_remaining(expires),
        })

    return status
