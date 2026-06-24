# PalayKita

Rice milling profit tracker for recording milling jobs, payments, customers,
commercial sack sales, printable tickets, and Excel reports.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Flask](https://img.shields.io/badge/Web-Flask-111827)
![SQLite](https://img.shields.io/badge/Database-SQLite-0f766e)
![Waitress](https://img.shields.io/badge/Server-Waitress-2563eb)
![Status](https://img.shields.io/badge/Mode-Offline%20First-16a34a)

PalayKita is a local-first business app for rice mills. It tracks local milling
transactions, commercial customer purchases, unpaid balances, payment history,
thermal-style tickets, audit logs, and reports. It runs on SQLite, serves a
Flask web app through Waitress for LAN/tablet access, and can also run inside a
desktop window.

> **Default login:** `admin` / `admin123` — change it on first login
> (Settings → change password) before using the app with real data.

## Table of Contents

- [Features](#features)
- [Transaction Calculations](#transaction-calculations)
- [Tech Stack](#tech-stack)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [First Launch](#first-launch)
- [Launch Modes](#launch-modes)
- [Configuration](#configuration)
- [Data, Reports, and Backups](#data-reports-and-backups)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Build a Desktop EXE](#build-a-desktop-exe)
- [Security / Privacy Note](#security--privacy-note)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Production Checklist](#production-checklist)

## Features

| Area | What PalayKita Provides |
| --- | --- |
| Local milling transactions | Record kilos milled, milling rate, optional chaff deduction, amount paid, and remaining balance. |
| Commercial transactions | Track registered commercial customers buying by sacks with price-per-sack billing. |
| Payment ledger | Record partial payments, mark balances paid, and preserve local/commercial payment history. |
| Unpaid tracking | View unpaid and partial accounts from a dedicated page and dashboard totals. |
| Dashboard | Monitor sales, cash collected, kilos milled, sacks sold, unpaid totals, and recent activity. |
| Reports | Generate daily, weekly, monthly, custom, commercial, and audit reports as Excel files. |
| Ticket printing | Show, reprint, and test 80 mm thermal-style customer tickets. |
| Commercial customers | Add, edit, deactivate, reactivate, and review customer transaction history. |
| Users and roles | Admin and staff roles with login protection and safeguards for keeping at least one active admin. |
| Audit log | Record meaningful actions with user, action type, and readable change details. |
| Licensing | Offline activation key flow locked to the machine Computer ID. |
| Settings | Business name, currency, rates, ticket text, commercial defaults, server port, reports, license, and user management. |
| LAN access | Serve the app to phones or tablets on the same Wi-Fi network. |

## Transaction Calculations

PalayKita uses `Decimal` with half-up rounding for money calculations.

Local milling transaction:

```text
gross_fee       = kilos_milled * milling_rate_per_kg
chaff_deduction = chaff_kilos * chaff_rate_per_kg
net_amount      = gross_fee - chaff_deduction
balance         = net_amount - amount_paid
status          = Paid, Partial, or Unpaid
```

Commercial transaction:

```text
total_amount = number_of_sacks * price_per_sack
balance      = total_amount - amount_paid
status       = Paid, Partial, or Unpaid
```

Over-payment is capped to the amount owed so cash-collected totals and reports
do not become inflated.

## Tech Stack

- Python 3.11+
- Flask and Flask-SQLAlchemy
- SQLite local database
- Waitress WSGI server for LAN/tablet access
- pywebview for optional desktop-window mode
- Tkinter for the server manager and standalone desktop app
- openpyxl for Excel report generation
- python-dotenv for environment configuration
- Werkzeug password hashing and route protection
- HMAC-SHA256 signed offline activation keys
- PyInstaller for Windows desktop packaging

Main dependencies are listed in [`requirements.txt`](requirements.txt).

## Requirements

| Requirement | Version |
| --- | --- |
| Python | 3.11 or newer |
| Operating system | Windows 10/11, macOS 12+, or Linux |
| Browser | Any modern browser for web/LAN mode |
| Storage | Local write access for `instance/`, `exports/`, and `backups/` |

## Quick Start

From the `PalayKita` project directory:

```bash
python -m venv venv
```

Activate the virtual environment:

```bash
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the web app:

```bash
python app.py
```

Open it on the same computer:

```text
http://localhost:5000
```

To use a phone or tablet, open the computer's LAN address, for example:

```text
http://192.168.1.23:5000
```

## First Launch

On first launch, PalayKita prepares the local app folders and database:

- Creates `instance/palaykita.db`
- Creates report folders under `exports/reports/`
- Creates `backups/`
- Creates all database tables
- Runs SQLite-safe migrations and default seeding
- Seeds default settings
- Seeds the default admin account

The normal first-run flow is:

1. Activate the app with a valid activation key.
2. Log in with the default admin account.
3. Change the default password in Settings.
4. Review business name, rates, ticket text, commercial defaults, and server
   port.

Default login:

```text
Username: admin
Password: admin123
```

Change this password before using the app with real mill data.

## Launch Modes

| Entry Point | Command | Best For |
| --- | --- | --- |
| Flask LAN server | `python app.py` | Main web app served by Waitress on `0.0.0.0:<port>` for local network access. |
| Server manager | `python launcher.py` | Tkinter GUI for starting/stopping/restarting the server, viewing logs, and copying LAN URLs. |
| Desktop window | `python desktop_app.py` | pywebview desktop shell using a private local server at `127.0.0.1:5050`. |
| Standalone Tkinter app | `python desktop.py` | Native-style desktop app that works directly with SQLite and can also start Wi-Fi sharing. |

Windows helper scripts are also included:

```bash
run_web.bat
run_desktop.bat
```

## Configuration

Environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `SECRET_KEY` | Flask session secret. Set this before real deployment. | `palaykita-local-secret-key-change-later` |
| `PALAYKITA_PORT` | Overrides the saved LAN server port. | `5000` |
| `PALAYKITA_DEBUG` | Enables Flask debug mode only when set to `1`, `true`, `yes`, or `on`. | Off |

Ports:

| Port | Purpose |
| --- | --- |
| `5000` | Default LAN/shared web server port. Configurable in Settings or with `PALAYKITA_PORT`. |
| `5050` | Private desktop-window port used by `desktop_app.py`. |

## Data, Reports, and Backups

| Path | Purpose |
| --- | --- |
| `instance/palaykita.db` | Main SQLite database. |
| `instance/license.json` | Local activation file after successful activation. |
| `exports/reports/daily/` | Daily Excel reports. |
| `exports/reports/weekly/` | Weekly Excel reports. |
| `exports/reports/monthly/` | Monthly Excel reports. |
| `exports/reports/custom/` | Custom date-range reports. |
| `exports/reports/commercial/` | Commercial customer and sack-sales reports. |
| `backups/` | Database backups. |

Keep database, license, backup, and generated report files out of public version
control.

## Project Structure

```text
PalayKita/
|-- app.py                    Flask/Waitress entry point
|-- launcher.py               Tkinter server manager
|-- desktop_app.py            pywebview desktop-window entry point
|-- desktop.py                standalone Tkinter desktop app
|-- config.py                 Flask config, paths, database URI, export folders
|-- reports.py                desktop report generation
|-- build_desktop.bat         Windows PyInstaller build helper
|-- palaykita_desktop.spec    PyInstaller spec
|-- requirements.txt          Python dependencies
|
|-- app/
|   |-- __init__.py           create_app(), app version, database setup
|   |-- auth.py               login, password hashing, role decorators
|   |-- calculations.py       Decimal-safe billing calculations
|   |-- desktop_export.py     desktop export helpers
|   |-- licensing.py          offline activation and Computer ID helpers
|   |-- models.py             users, settings, transactions, payments, audit log
|   |-- reports.py            Excel report builders
|   |-- routes.py             web routes for dashboard, transactions, settings, reports
|   |-- seed.py               default admin/settings and migrations
|   |-- server_control.py     LAN server start/stop and port helpers
|   `-- utils.py              folder, settings, formatting, and utility helpers
|
|-- database/                 direct SQLite engine/models for desktop mode
|-- templates/                Jinja pages
|-- static/                   CSS, JavaScript, icons, and brand assets
|-- tests/                    unittest coverage for billing, dashboard, tickets, audit, UI rules
|-- web/                      static web wrapper assets
|-- instance/                 runtime database and license file
|-- exports/                  generated report files
`-- backups/                  database backups
```

## Testing

Run the test suite from the project directory:

```bash
python -m unittest discover -s tests
```

The tests cover important behavior such as:

- dashboard totals
- commercial customer workflows
- audit log features
- payment capping
- local customer defaults
- local ticket printing
- login branding
- table layout
- settings/about information

## Build a Desktop EXE

On Windows, run:

```bash
build_desktop.bat
```

The script creates a virtual environment if needed, installs requirements,
installs PyInstaller, and runs:

```bash
pyinstaller palaykita_desktop.spec --clean --noconfirm
```

The bundled spec intentionally creates timestamped output folders by default so
an older open build does not block a rebuild.

## Security / Privacy Note

Runtime data, databases, generated reports, backups, logs, license keys, and
private records are excluded from this repository for security and privacy
reasons.

Use `.env.example` as a template for local secrets. Copy it to `.env`, fill in
local values, and keep `.env` out of Git.

## Security Notes

- Debug mode is off by default.
- Passwords are hashed with Werkzeug.
- Login is required for protected pages.
- Admin-only routes are guarded.
- The app prevents removing the last active admin account.
- Report download/delete routes use path containment checks.
- Payment calculations cap over-payment.
- Activation keys are signed and locked to the machine Computer ID.

Before real deployment, set a strong `SECRET_KEY` environment variable.

## Troubleshooting

| Problem | Suggested Fix |
| --- | --- |
| `ModuleNotFoundError` after running the app | Activate the virtual environment and run `pip install -r requirements.txt`. |
| Phone cannot open the app | Make sure the phone and computer are on the same Wi-Fi network and that the firewall allows the configured port. |
| Port is already in use | Change the server port in Settings or set `PALAYKITA_PORT` before launching. |
| Desktop window falls back to browser | Install/check `pywebview`, or use the browser fallback URL printed in the terminal. |
| Login fails on a fresh install | Confirm the default account exists and try `admin` / `admin123`; otherwise remove only a disposable test database and relaunch. |
| Report file will not delete | Close the file in Excel or any other program, then try again. |

## Production Checklist

- Change the default `admin` / `admin123` password.
- Set a strong `SECRET_KEY` environment variable.
- Keep `instance/palaykita.db`, `instance/license.json`, `backups/`, and
  generated reports out of public GitHub repositories.
- Create regular off-machine backups of `instance/palaykita.db`.
- Test activation, login, transaction entry, partial payments, ticket printing,
  reports, backup, restore, and LAN access before live use.

## Author

Created by **John Lloyd Sereno (toshfry)**.
