# API Contract (Thunkable + Supabase + Replicate)

This document defines strict request/response contracts for cloud mode.

## Base

- Base URL: `https://<project-ref>.supabase.co/functions/v1`
- Auth headers:
  - `apikey: <SUPABASE_ANON_KEY>`
  - `Authorization: Bearer <SUPABASE_JWT or ANON_KEY for testing>`
- Content type: `application/json`

## Endpoint 1: Render (v1)

- Method: `POST`
- Path: `/render`
- Purpose: Prompt/style render from input image with optional reference/mask.

### Request body

```json
{
  "user_id": "uuid-required",
  "prompt": "string-required-1-1200",
  "style": "string-optional-max-200",
  "input_image_url": "https-url-optional",
  "reference_image_url": "https-url-optional",
  "mask_url": "https-url-optional",
  "consistency_key": "string-optional",
  "strict_consistency": true,
  "model": "string-optional",
  "num_outputs": 1
}
```

### Validation rules

- `user_id` required, UUID format.
- `prompt` required, non-empty, max 1200 chars.
- `num_outputs` optional, allowed range `1..4`.
- At least one of `input_image_url` or `prompt` must exist (prompt is already required in v1).
- URLs must be HTTPS and publicly accessible by the function runtime.

### Success response (200)

```json
{
  "request_id": "uuid",
  "status": "completed",
  "image_url": "https://.../storage/v1/object/public/renders/<user>/<request>.png"
}
```

### Error responses

- `400` invalid payload
- `401` unauthorized
- `405` method not allowed
- `429` quota exceeded (recommended next guardrail)
- `500` provider/runtime failure

Example error payload:

```json
{
  "request_id": "uuid-or-null",
  "status": "failed",
  "error": "human-readable-message"
}
```

## Endpoint 2: Regional Edit (scaffolded)

- Method: `POST`
- Path: `/edit-regional`
- Purpose: Left-right editing with category-based transformation and region control.

Implementation note:

- A working scaffold exists in `supabase/functions/edit-regional/index.ts`.
- It validates payloads, calls Replicate, stores outputs in Supabase Storage, and writes metadata.

### Request body

```json
{
  "user_id": "uuid-required",
  "target_image_url": "https-url-required",
  "reference_image_url": "https-url-optional",
  "prompt": "string-optional-max-1200",
  "edit_category": "element_texture|whole_building|prompt_only",
  "region_hint": "auto|facade|roof|windows|entry|balcony|ground-floor|upper-floor|landscape|interior-zone",
  "selection_mode": "automatic|manual",
  "target_mask_url": "https-url-optional",
  "target_mask_data_url": "data:image/png;base64,... (optional)",
  "reference_mask_url": "https-url-optional",
  "strict_consistency": true,
  "model_profile": "fast|balanced|quality",
  "strength": 0.65
}
```

### Validation rules

- `target_image_url` required.
- `edit_category` required.
- If `edit_category = prompt_only`, `prompt` required.
- If `selection_mode = manual`, at least one of `target_mask_url` or `target_mask_data_url` is required.
- `strength` range `0.0..1.0`.

Consistency notes:

- Set `strict_consistency: true` for production runs where the same building identity must be preserved.
- Pass one stable `consistency_key` across related view renders so model selection stays deterministic for that package.

### Success response (200)

```json
{
  "request_id": "uuid",
  "status": "completed",
  "image_url": "https://...png",
  "applied_region": {
    "mode": "automatic",
    "coverage_ratio": 0.18
  },
  "edit_summary": {
    "category": "element_texture",
    "target": "roof",
    "changes": ["material", "color"]
  }
}
```

### Async option (recommended for slower models)

For long renders, return `202`:

```json
{
  "request_id": "uuid",
  "status": "processing",
  "poll_url": "/functions/v1/render-status?request_id=uuid"
}
```

## Endpoint 3: Render Status (v1.1 planned)

- Method: `GET`
- Path: `/render-status?request_id=<uuid>`
- Purpose: Poll request status for async jobs.

### Success response (200)

```json
{
  "request_id": "uuid",
  "status": "queued|processing|completed|failed",
  "image_url": "https://...png",
  "error": null
}
```

## Endpoint 4: User Render History (v1.1 planned)

- Method: `GET`
- Path: `/render-history?limit=20&offset=0`
- Purpose: Return latest user jobs/results.

### Success response (200)

```json
{
  "items": [
    {
      "request_id": "uuid",
      "created_at": "2026-03-09T12:00:00Z",
      "status": "completed",
      "prompt": "...",
      "image_url": "https://...png"
    }
  ],
  "limit": 20,
  "offset": 0,
  "total_estimate": 145
}
```

## Thunkable integration contract

Required Thunkable app fields:

- `user_id`
- `target image`
- `reference image` (optional for v1, recommended for v1.1)
- `prompt`
- `style`
- `selection mode` (v1.1)
- `generate action`

Recommended client behavior:

1. Disable generate button while request is active.
2. Show spinner and status text.
3. Retry once on transient `5xx`.
4. Surface provider errors directly to user in plain language.

## Versioning policy

- Keep `/render` backward compatible.
- Introduce new behavior via new endpoints or optional fields.
- Include `X-API-Version` response header in future revisions.

## Security and budget guardrails

- Enforce JWT auth on all endpoints in production.
- Rate limit by `user_id` and IP.
- Add daily render quota per user.
- Restrict max image resolution and prompt length.
- Log request timing and provider cost metadata per job.