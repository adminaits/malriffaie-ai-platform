# Malriffaie AI Customer Support + E-commerce Platform

This starter codebase implements the attached prompt as a deployable foundation:

- FastAPI backend for Render
- React/Vite frontend for Vercel
- Supabase SQL schema and seed products
- Hugging Face configurable chat/RAG flow
- Public chat, product/service sidebar, product recommendations
- Admin CRUD dashboard for the requested sections
- Admin email/password login with JWT protection and change-password option
- Stubs for Google Drive, Google Calendar, Tap payment, and email integrations

## 1. Supabase setup

1. Create a Supabase project.
2. Open SQL Editor.
3. Run `supabase/schema.sql`.
4. Copy `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_ANON_KEY`.
5. The backend will create the first admin automatically from `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` when the `admin_users` table is empty.

## 2. Backend local setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## 3. Frontend local setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## 4. Render deployment

Create a Render Web Service from the `backend` folder.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Add the backend environment variables from `backend/.env.example`, especially:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_ANON_KEY=...
JWT_SECRET=use-a-long-random-secret
DEFAULT_ADMIN_EMAIL=admin@aits.cc
DEFAULT_ADMIN_PASSWORD=Aits123!
```

After first login, open `/admin`, click **Change Password**, and replace the temporary password.

## 5. Vercel deployment

Create a Vercel project from the `frontend` folder.

Set:

```bash
VITE_API_URL=https://YOUR_RENDER_BACKEND_URL
```

## Production hardening still needed

This is a strong starter/MVP codebase, not a complete audited production system. Before launch, add:

- Role-based permissions beyond the initial admin role
- Encrypted storage for Hugging Face, Google, Tap, and email credentials
- pgvector embeddings and semantic search RPC for stronger RAG
- Real Google Drive document extraction/chunking
- Real Google Calendar freebusy and event creation
- Real Tap payment charge/session creation and webhook verification
- SMTP/email provider integration
- Row Level Security policies in Supabase
- File upload scanning and strict validation
- Automated tests and CI


## Admin AI model controls
The `/admin` dashboard includes AI Concierge Settings with:
- Hugging Face access token
- Chat model dropdown
- Custom chat model name
- Custom Hugging Face-compatible endpoint URL
- Embedding model dropdown
- Custom embedding model name
- Custom embedding endpoint URL

For an existing Supabase project, run the latest `supabase/schema.sql` or run this migration manually:

```sql
alter table ai_settings add column if not exists custom_embedding_model_name text;
```

## Latest frontend homepage update

- The root path `/` opens the full-page AI chat interface directly.
- `/admin` opens the protected admin dashboard.
- The chat screen uses a dark sidebar layout similar to the provided reference image.
- Chat sidebar includes brand block, New chat button, Services, and Products.
- Product list and product detail answers are formatted deterministically with clean line breaks and `300.000 BHD` price format.

## Client registration and dashboard update

This version adds a client portal in addition to the admin dashboard:

- Homepage `/` remains the chat-enabled homepage.
- Homepage header includes **Client Registration** and **Client Login** links.
- `/client-register` allows a client to create an account with name, email, password, company name, and phone.
- Client registration also creates a lead record in the `leads` table with status `registered` for admin follow-up.
- `/client-login` allows registered clients to log in.
- `/client-dashboard` is a protected client dashboard with a chat-enabled support widget, client details, product list, and services list.

For existing Supabase projects, run the latest `supabase/schema.sql` again or run these safe migrations manually:

```sql
alter table users add column if not exists name text;
alter table users add column if not exists company_name text;
alter table users add column if not exists phone text;
alter table users add column if not exists is_active boolean default true;
alter table users add column if not exists updated_at timestamptz default now();
```

Client auth API endpoints:

```text
POST /api/auth/client/register
POST /api/auth/client/login
GET  /api/auth/client/me
POST /api/auth/client/change-password
```
