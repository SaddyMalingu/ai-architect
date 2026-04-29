# AI Architect

This repository now supports two parallel stacks:

1. Local stack (existing): FastAPI + local pipeline in `src/`
2. Cloud beginner stack (new): Thunkable + Supabase + Replicate

## Cloud beginner stack files

- `supabase/migrations/20260309_beginner_stack.sql` - tables, RLS, storage policies
- `supabase/functions/render/index.ts` - Supabase Edge Function calling Replicate
- `supabase/functions/edit-regional/index.ts` - Supabase Edge Function for regional editing flow
- `.env.example` - required environment variables
- `docs/SUPABASE_REPLICATE_SETUP.md` - end-to-end setup guide
- `docs/API_CONTRACT.md` - strict payload/response contracts
- `docs/BLENDER_CONSISTENCY_MODE.md` - exact Blender-conditioned workflow for maximum consistency
- `docs/BLENDER_TEST_RUN_SHEET.md` - one-page execution sheet for strict consistency test runs

## Local stack quick run

- Backend: `python -m uvicorn src.server:app --reload --host 0.0.0.0 --port 8000`
- Frontend viewer: `cd ui && npx http-server -c-1 . -p 8080`

### UI non-regression workflow

- Generate redirect shim for alternate entry route:
	- `cd ui && npm run sync:ui`
- Run UI compatibility smoke checks before deploy:
	- `cd ui && npm run smoke:ui`
- One-command predeploy gate (recommended):
	- `cd ui && npm run predeploy`

The smoke check verifies required controls/IDs, endpoint references, and that
`ui/cloud_demo.html` remains a redirect shim to canonical `ui/index.html`.

## Cloud stack quick run (Supabase)

1. Create a Supabase project and storage bucket `renders`.
2. Run SQL in `supabase/migrations/20260309_beginner_stack.sql`.
3. Deploy Edge Function from `supabase/functions/render/index.ts`.
4. Deploy Edge Function from `supabase/functions/edit-regional/index.ts`.
4. Set function secrets from `.env.example`.
5. Call endpoints from Thunkable:

`POST https://<project-ref>.supabase.co/functions/v1/render`

`POST https://<project-ref>.supabase.co/functions/v1/edit-regional`

See `docs/SUPABASE_REPLICATE_SETUP.md` for exact payloads and steps.

For production-level consistency (including interiors), use `docs/BLENDER_CONSISTENCY_MODE.md`.
For immediate execution, use `docs/BLENDER_TEST_RUN_SHEET.md`.
