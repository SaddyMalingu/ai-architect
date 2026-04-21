# Blender-Conditioned Consistency Mode

This guide provides a strict workflow for keeping the same building identity across repeated renders and regional edits, including interiors.

## Goal

Lock geometry and camera decisions in Blender, then use the cloud pipeline for texture, mood, and detail refinement.

## Mode definition

Use this mode when all of the following must stay stable:

- Building massing and proportions
- Opening layout (doors, windows)
- Camera framing
- Primary material families
- Floor-to-floor hierarchy (especially for interior view continuity)

## 1) Blender scene setup (exact baseline)

Create one master Blender file per project and keep these fixed across all runs:

- Unit system: Metric
- Length: Meters
- Scale: 1.0
- World origin: Building centerline on X=0, Y=0
- Building forward axis: +Y

### Camera rig (recommended defaults)

Create and save these camera objects:

- CAM_FRONT_EXTERIOR
- CAM_LEFT_EXTERIOR
- CAM_RIGHT_EXTERIOR
- CAM_BACK_EXTERIOR
- CAM_LOBBY_INTERIOR
- CAM_LIVING_INTERIOR
- CAM_KITCHEN_INTERIOR
- CAM_BEDROOM_INTERIOR

Use the same camera properties for each family:

Exterior camera defaults:

- Focal length: 35 mm
- Sensor fit: Horizontal
- Camera height: 1.60 m
- Pitch: 0 to -3 deg (very slight down tilt)
- Roll: 0 deg

Interior camera defaults:

- Focal length: 24 to 28 mm (pick one and keep fixed per room family)
- Sensor fit: Horizontal
- Camera height: 1.50 m
- Pitch: -2 to -5 deg
- Roll: 0 deg

Framing rule:

- Keep 5 to 8 percent visual margin around target architecture to reduce edge hallucinations.

## 2) Required base passes per camera

Export these files per camera view:

- Beauty pass: final lit render at target framing
- Clay pass: neutral material geometry anchor
- Line pass: Freestyle or edge render for opening and silhouette guidance
- Depth pass: normalized Z-depth (16-bit PNG or EXR)
- Material ID mask pass: facade zones or interior zones (wall, floor, joinery, glazing)

Recommended resolution:

- Exterior: 1536x1024
- Interior: 1536x1024 or 1344x896

Naming convention:

- <project>_<camera>_beauty.png
- <project>_<camera>_clay.png
- <project>_<camera>_line.png
- <project>_<camera>_depth.png
- <project>_<camera>_mask_<zone>.png

## 3) How to feed into this pipeline

Use the cloud UI and API with consistency controls enabled.

Render endpoint payload guidance:

- input_image_url: Blender beauty pass for that exact camera
- reference_image_url: style board or approved previous hero render
- consistency_key: one stable key for the entire building package, for example project_name plus revision
- strict_consistency: true
- model_profile: balanced or quality (balanced during low-credit periods)

Regional edit endpoint payload guidance:

- target_image_url: current approved render for that camera
- target_mask_data_url or target_mask_url: constrained area to modify
- region_hint: facade, windows, entry, balcony, roof, ground-floor, upper-floor, interior-zone
- strict_consistency: true
- strength: 0.35 to 0.60 for structural preservation

## 4) UI workflow (recommended sequence)

1. Turn Consistency mode on.
2. Keep one fixed prompt family per project revision.
3. Load Blender beauty pass into Image to render URL.
4. Load one stable style reference into Reference image URL.
5. Run one view first (not all views) and approve.
6. Run remaining views only after first-view approval.
7. Use Regional Edit for localized changes instead of full rerender.

## 5) Low-credit safe mode

Until credit is restored, use:

- model_profile: balanced
- num_outputs: 1
- run views sequentially
- avoid unnecessary all-view reruns
- prefer regional edit over full rerender

## 6) Interior consistency rules

For interior continuity, lock these in Blender before any generation:

- Same room envelope dimensions
- Fixed camera per room family
- Fixed window and door placements
- Fixed major furniture anchors (even proxy boxes)
- Fixed key lights and window daylight direction

Then use AI to refine:

- Texture quality
- Material nuance
- Decorative details
- Atmosphere and grading

Do not ask AI to redesign room geometry if consistency is the objective.

## 7) Quality gate checklist

Approve a render only if all pass:

- Openings match Blender layout
- Floor-to-ceiling proportions unchanged
- Camera framing unchanged
- Core materials remain in family
- Unselected regions remain untouched after regional edit

If two or more fail, rerender from Blender-conditioned input, not from prompt-only input.

## 8) Drift scoring (for repeat test runs)

Score each output from 0 to 5 per item:

- Geometry match
- Opening layout match
- Camera framing match
- Material family match
- Regional edit containment

Target: 23 to 25 out of 25 for production acceptance.

## 9) Operational recommendation

Maintain two operating modes:

- Ideation mode: prompt-first, lower consistency expectations
- Production mode: Blender-conditioned, strict consistency true, regional edits for local deltas only

For your next test, use production mode only.