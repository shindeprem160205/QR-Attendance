# QR Code Based Attendance System

A small **Flask** web app for instructors to run a class session, show a **time-limited QR code**, and for students to **scan with the device camera** (phone or laptop) to record attendance. Works on modern mobile and desktop browsers over **HTTPS** (required for camera access on many devices).

## Project layout

```
qr attendance/
├── app.py                 # Flask routes, QR logic, CSV export, CLI commands
├── config.py              # Environment-based settings (DB, secrets, timeouts)
├── models.py              # User, LectureSession, Attendance (SQLAlchemy)
├── requirements.txt
├── Procfile               # Render / gunicorn entry: web: gunicorn app:app
├── runtime.txt            # Optional Python version hint for hosts
├── .env.example           # Copy to .env for local configuration
├── instance/              # Created automatically; holds SQLite DB locally
├── static/
│   ├── css/style.css
│   └── js/scanner.js      # html5-qrcode integration + /student/mark API
└── templates/
    ├── base.html
    ├── login.html
    ├── register.html
    ├── admin/
    │   ├── dashboard.html
    │   ├── session_qr.html
    │   └── attendance.html
    ├── student/
    │   └── dashboard.html
    └── errors/
        ├── 404.html
        └── 500.html
```

## How it works (short)

1. **QR payload** is plain text: `session_id|unix_timestamp_utc` (generated with the `qrcode` library).
2. When a student scans, **html5-qrcode** reads that string and `fetch`es `POST /student/mark` with JSON `{ "qr_text": "..." }`.
3. The server checks: **session exists**, **timestamp is within `QR_VALIDITY_SECONDS` (default 300 = 5 minutes)**, and **no duplicate** row for that user + session (`UniqueConstraint`).
4. **Passwords** are stored with **Werkzeug** `generate_password_hash` / `check_password_hash`.
5. **Logged-in session timeout** uses Flask’s `PERMANENT_SESSION_LIFETIME` (`SESSION_TIMEOUT_MINUTES`).

## Run locally (Windows / macOS / Linux)

### 1. Python 3.11+ recommended

```bash
cd "path/to/qr attendance"
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment file

Copy `.env.example` to `.env` and set at least:

- `SECRET_KEY` — long random string (required for real use).

Optional:

- `ADMIN_REGISTRATION_SECRET` — if set, a user who enters this exact value in the “Admin secret” field on **Register** becomes an **admin**. If unset, only the CLI can create admins.
- `SESSION_TIMEOUT_MINUTES` — browser session length (default `60`).
- `QR_VALIDITY_SECONDS` — QR freshness window (default `300`).

### 3. Initialize database and create an admin

Without `DATABASE_URL`, the app uses **SQLite** at `instance/attendance.db` (path is absolute so it works from any working directory).

```bash
flask --app app init-db
flask --app app create-admin --email you@example.com --password yourpassword --name "Your Name"
```

### 4. Start the dev server

```bash
flask --app app run --debug
```

Open `http://127.0.0.1:5000`. **Camera scanning often requires HTTPS**; locally, some browsers allow `http://localhost`, others do not. For reliable camera tests, deploy to Render (HTTPS) or use a local HTTPS tunnel (e.g. ngrok).

### 5. Typical flow

1. Log in as **admin** → create a **session** → open **Show QR** (page auto-refreshes the image).
2. Register / log in as a **student** on another device or browser → **Start camera** → scan the QR.
3. Admin views **Records** or downloads **CSV**.

## PostgreSQL (cloud)

Set `DATABASE_URL` to your provider’s connection string (Render sets this automatically when you attach a PostgreSQL instance). The app rewrites legacy `postgres://` URLs to `postgresql://` for SQLAlchemy.

## Deploy on Render (step by step)

1. **Push this folder to GitHub** (or GitLab / Bitbucket) as a repository Render can access.
2. In the [Render dashboard](https://dashboard.render.com/), click **New +** → **Web Service**.
3. Connect the repository and choose the branch to deploy.
4. Configure the service:
   - **Runtime**: Python 3
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn app:app` (matches the included `Procfile`)
5. **Add environment variables** (Render → your Web Service → **Environment**):
   - `SECRET_KEY` — generate a long random string (do not reuse the dev default).
   - Optional: `ADMIN_REGISTRATION_SECRET`, `SESSION_TIMEOUT_MINUTES`, `QR_VALIDITY_SECONDS`.
6. **(Recommended)** **New +** → **PostgreSQL**. After it is created, copy the **Internal Database URL** (or use Render’s “Link database” so `DATABASE_URL` is injected). Ensure `DATABASE_URL` appears in the **web service** environment.
7. **First deploy**: after the build succeeds, open **Shell** for the web service (or use a one-off job) and run:

   ```bash
   flask --app app init-db
   flask --app app create-admin --email you@example.com --password yourpassword --name "Admin"
   ```

8. Open the **Render HTTPS URL** for your service. Use **HTTPS** so student devices can use the camera.

### Notes for Render

- `runtime.txt` suggests Python **3.11.9**; Render may map it to a close available patch version.
- **Gunicorn** is Linux-oriented; on Render’s containers it is the standard way to run Flask (see `Procfile`).
- Keep **PostgreSQL** and the **web service** in the same region for lower latency.

## Environment variables (reference)

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Flask session signing (required in production) |
| `DATABASE_URL` | PostgreSQL connection string; omit for SQLite |
| `ADMIN_REGISTRATION_SECRET` | Optional shared secret to register as admin |
| `SESSION_TIMEOUT_MINUTES` | Logged-in session lifetime |
| `QR_VALIDITY_SECONDS` | Max age of embedded QR timestamp (default 300) |

## Security notes (production)

- Always set a strong `SECRET_KEY`.
- Prefer **PostgreSQL** on a managed host over SQLite for concurrent web workers.
- Serve only over **HTTPS** so cookies and camera APIs behave as expected.
- Treat `ADMIN_REGISTRATION_SECRET` like a password; rotate if leaked.

## License

Use and modify freely for teaching and internal projects.
