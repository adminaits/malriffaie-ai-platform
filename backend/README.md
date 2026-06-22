# Backend

FastAPI backend for Render.

## Local run
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Render start command
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set all `.env.example` variables in Render Environment Variables.

## Admin login

The admin API is protected by JWT Bearer authentication.

Default first admin, created automatically when `admin_users` is empty:

```bash
DEFAULT_ADMIN_EMAIL=admin@aits.cc
DEFAULT_ADMIN_PASSWORD=Aits123!
```

Set a strong `JWT_SECRET` in Render and change the temporary password from the admin dashboard immediately after first login.
