# Blender Consistency Test Run Sheet

Use this sheet for one strict production test cycle.

## Test identity

- Project name: ______________________
- Revision tag: ______________________
- User UUID: `ec470708-d89c-4575-9d94-b57cd681bb8b`
- Date/time: ______________________
- Operator: ______________________

## Fixed consistency values

Keep these identical for every related render in this run.

- consistency_key: `<project_name>|<revision_tag>`
- strict_consistency: `true`
- model_profile: `balanced` (or `quality` only if credit allows)
- num_outputs: `1`
- Backend API Base (Control Room): `https://eccvtkqkllegzbypaemw.supabase.co/functions/v1`

## Blender prep checklist (must be done first)

- [ ] Cameras are fixed and saved (no lens or transform changes)
- [ ] Exterior cameras: 35mm, ~1.60m eye height
- [ ] Interior cameras: fixed room-specific focal length (24-28mm)
- [ ] Same scene lighting baseline is used
- [ ] Base passes exported for each required camera
- [ ] Filenames follow the project camera naming scheme

## Input mapping per camera

Fill this before running anything.

### Exterior

- CAM_FRONT_EXTERIOR beauty URL: ______________________
- CAM_LEFT_EXTERIOR beauty URL: ______________________
- CAM_RIGHT_EXTERIOR beauty URL: ______________________
- CAM_BACK_EXTERIOR beauty URL: ______________________

### Interior

- CAM_LOBBY_INTERIOR beauty URL: ______________________
- CAM_LIVING_INTERIOR beauty URL: ______________________
- CAM_KITCHEN_INTERIOR beauty URL: ______________________
- CAM_BEDROOM_INTERIOR beauty URL: ______________________

### Style reference

- Stable style/reference image URL: ______________________

## UI run steps (strict order)

1. Hard refresh live UI.
2. Confirm Consistency mode is ON.
3. Keep one prompt family for the whole run (do not rewrite style terms mid-run).
4. Set input image URL to one camera beauty pass.
5. Set reference image URL to one stable style reference.
6. Run single view first.
7. Approve first view against checklist below.
8. Run remaining related views sequentially.
9. Use Regional Edit only for local changes (no full rerender unless required).

## Render payload template (for debugging/manual call)

`POST /functions/v1/render`

```json
{
  "user_id": "ec470708-d89c-4575-9d94-b57cd681bb8b",
  "prompt": "<fixed project prompt family>",
  "style": "photoreal exterior",
  "input_image_url": "<blender_beauty_url>",
  "reference_image_url": "<stable_style_reference_url>",
  "model_profile": "balanced",
  "consistency_key": "<project_name>|<revision_tag>",
  "strict_consistency": true,
  "num_outputs": 1
}
```

## Regional edit payload template (manual precise region)

`POST /functions/v1/edit-regional`

```json
{
  "user_id": "ec470708-d89c-4575-9d94-b57cd681bb8b",
  "target_image_url": "<current_approved_render_url>",
  "reference_image_url": "<stable_style_reference_url>",
  "prompt": "<localized edit instruction>",
  "edit_category": "element_texture",
  "region_hint": "facade",
  "selection_mode": "manual",
  "target_mask_data_url": "data:image/png;base64,<from-ui-mask>",
  "strict_consistency": true,
  "model_profile": "balanced",
  "strength": 0.45
}
```

## Approval checklist per output

- [ ] Geometry matches Blender base
- [ ] Window/door layout unchanged
- [ ] Camera framing unchanged
- [ ] Core material family preserved
- [ ] Unselected regions unchanged after regional edit

## Drift score card (0-5 each)

- Geometry match: __
- Opening layout match: __
- Framing match: __
- Material family match: __
- Edit containment: __

Total: __ / 25

Production pass target: `23+ / 25`

## Low-credit fallback mode

If credits are constrained during testing:

- Use `model_profile = balanced`
- Keep `num_outputs = 1`
- Run one view at a time
- Prefer regional edits over full rerenders
- Skip non-critical camera variants
