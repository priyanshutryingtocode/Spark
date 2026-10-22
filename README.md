# Spark

Creator and early-stage company discovery from plain-language briefs.

## Run locally

Requirements: Python 3.12+, Node.js, PostgreSQL with `pgvector`, and a Gemini API key.

Create a root `.env` with `DATABASE_URL` and `GEMINI_API_KEY`. Add `SUPABASE_URL` and `SUPABASE_JWT_SECRET` when using authentication.

```bash
# Backend
cd backend
python -m pip install -r requirements.txt
uvicorn api.main:app --reload

# Frontend (in another terminal)
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_ANON_KEY` in `frontend/.env.local`.
