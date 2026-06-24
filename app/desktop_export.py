"""
app/desktop_export.py - Desktop-only report export helpers.

Desktop mode should export Excel reports to a user-selected folder/file instead
of forcing a browser download. Web/mobile mode still uses normal downloads.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple


def _default_export_dir() -> Path:
    home = Path.home()
    downloads = home / "Downloads"
    desktop = home / "Desktop"

    if downloads.exists():
        return downloads
    if desktop.exists():
        return desktop
    return home


def _open_folder(path: Path) -> None:
    """Open the folder in the OS file manager when possible."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def export_report_file(source_path: Path) -> Tuple[bool, str]:
    """
    Ask the desktop user where to export a report, then copy the generated XLSX.

    If the native Save As dialog is unavailable, a safe fallback export folder is
    created on the user's Desktop or home folder.
    """
    source_path = Path(source_path)

    if not source_path.exists():
        return False, "Report file was not found."

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()

        destination = filedialog.asksaveasfilename(
            parent=root,
            title="Export PalayKita Excel Report",
            initialdir=str(_default_export_dir()),
            initialfile=source_path.name,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")],
        )

        root.destroy()

        if not destination:
            return False, "Export cancelled."

        destination_path = Path(destination)
        if destination_path.suffix.lower() != ".xlsx":
            destination_path = destination_path.with_suffix(".xlsx")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        _open_folder(destination_path.parent)

        return True, f"Report exported successfully to: {destination_path}"

    except Exception as exc:
        fallback_dir = _default_export_dir() / "PalayKita Exports"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        destination_path = fallback_dir / source_path.name
        shutil.copy2(source_path, destination_path)
        _open_folder(destination_path.parent)

        return True, (
            f"Report exported to: {destination_path}. "
            f"The Save As dialog was unavailable ({exc})."
        )
