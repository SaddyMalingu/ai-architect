import hashlib
import json
import os
from typing import Any, Dict, List


def _hash_int(*parts: Any) -> int:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _pick(options: List[Any], *parts: Any) -> Any:
    if not options:
        raise ValueError("options cannot be empty")
    return options[_hash_int(*parts) % len(options)]


def _fraction(*parts: Any) -> float:
    return (_hash_int(*parts) % 10_000) / 10_000.0


def _window_bays(count: int, spread: float, width_ratio: float, skew: float = 0.0, shutters: bool = False) -> List[Dict[str, Any]]:
    if count <= 0:
        return []
    if count == 1:
        offsets = [skew]
    else:
        step = (spread * 2) / max(count - 1, 1)
        offsets = [(-spread + step * index) + skew for index in range(count)]
    bays = []
    for offset in offsets:
        bays.append(
            {
                "offset_ratio": round(offset, 3),
                "width_ratio": round(width_ratio, 3),
                "height_ratio": 0.32,
                "shutters": shutters,
            }
        )
    return bays


def build_house_identity(specs: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    specs = specs or {}
    materials = specs.get("materials") or {}
    site = specs.get("site") or {}
    floors = max(1, int(specs.get("floors", 1) or 1))
    window_pattern = str(specs.get("window_pattern") or "symmetrical").lower()
    base_seed = _hash_int(prompt, json.dumps(specs, sort_keys=True))

    garage_enabled = bool(specs.get("garage", True))
    porch_enabled = bool(specs.get("porch", True))
    dormer_enabled = bool(specs.get("dormer", False))

    # Check for LLM-proposed facades
    facades_cfg = specs.get("facades") or {}
    gable_facade = str(facades_cfg.get("gable_facade", "")).lower()
    secondary_side = str(facades_cfg.get("secondary_volume_side", "")).lower()
    llm_entry_offset = facades_cfg.get("entry_offset")

    if window_pattern == "asymmetrical":
        entry_offset_ratio = round(float(llm_entry_offset) if llm_entry_offset is not None else (_fraction(base_seed, "entry-offset") - 0.5) * 0.32, 3)
        front_count = 3
        rear_count = 2 + floors
        side_count = 2
        front_skew = round((_fraction(base_seed, "front-skew") - 0.5) * 0.18, 3)
    else:
        entry_offset_ratio = 0.0
        front_count = 2 if floors == 1 else 3
        rear_count = 2 if floors == 1 else 3
        side_count = 1 if floors == 1 else 2
        front_skew = 0.0

    # Determine garage side (LLM can propose or use deterministic default)
    garage_side = _pick(["left", "right"], base_seed, "garage-side") if garage_enabled else "none"
    
    # If LLM didn't propose secondary side, balance it opposite garage
    if not secondary_side or secondary_side not in ("left", "right"):
        secondary_side = "right" if garage_side == "left" else "left"
    
    # If LLM didn't propose gable, pick deterministically
    if not gable_facade or gable_facade not in ("front", "rear"):
        gable_facade = _pick(["front", "rear"], base_seed, "gable-facade")
    
    driveway_offset_ratio = entry_offset_ratio if garage_side == "none" else (-0.22 if garage_side == "left" else 0.22)
    dormer_offset_ratio = round((_fraction(base_seed, "dormer-offset") - 0.5) * 0.22, 3)

    identity = {
        "version": 1,
        "canonical_id": f"house-{base_seed % 1_000_000:06d}",
        "identity_seed": base_seed,
        "source_prompt": prompt,
        "style": specs.get("style", "modern"),
        "massing": {
            "floors": floors,
            "secondary_volume_side": secondary_side,
            "secondary_volume_width_ratio": 0.45,
            "secondary_volume_depth_ratio": 0.45,
            "secondary_volume_offset_ratio": 0.35,
        },
        "roof": {
            "type": specs.get("roof_type", "gable"),
            "gable_facade": gable_facade,
            "ridge_axis": "x",
            "overhang": 0.3,
            "dormer_enabled": dormer_enabled,
            "dormer_offset_ratio": dormer_offset_ratio,
        },
        "entry": {
            "porch_enabled": porch_enabled,
            "door_width": 1.2,
            "door_height": 2.2,
            "door_offset_ratio": entry_offset_ratio,
            "porch_width_ratio": 0.55,
            "porch_depth": 1.8,
        },
        "garage": {
            "enabled": garage_enabled,
            "side": garage_side,
            "width_ratio": 0.5,
            "depth_ratio": 0.5,
            "front_offset_ratio": 0.1,
        },
        "materials": {
            "wall": materials.get("wall", "stucco"),
            "roof": materials.get("roof", "shingle"),
            "trim": materials.get("trim", "white"),
            "window": materials.get("window", "clear"),
        },
        "site": {
            "driveway": bool(site.get("driveway", True)),
            "driveway_offset_ratio": round(driveway_offset_ratio, 3),
            "trees": max(0, int(site.get("trees", 2) or 0)),
            "tree_arc_ratio": 0.9,
        },
        "facades": {
            "front": {
                "window_bays": _window_bays(front_count, 0.28, 0.17, skew=front_skew, shutters=True),
                "accent": gable_facade == "front",
                "door_offset_ratio": entry_offset_ratio,
            },
            "rear": {
                "window_bays": _window_bays(rear_count, 0.3, 0.16, skew=-front_skew * 0.5),
                "accent": gable_facade == "rear",
                "door_offset_ratio": round(entry_offset_ratio * 0.5, 3),
            },
            "left": {
                "window_bays": _window_bays(side_count, 0.22, 0.16, skew=-0.04 if secondary_side == "left" else 0.02),
                "accent": secondary_side == "left",
            },
            "right": {
                "window_bays": _window_bays(side_count, 0.22, 0.16, skew=0.04 if secondary_side == "right" else -0.02),
                "accent": secondary_side == "right",
            },
        },
    }
    return identity


def save_house_identity(identity: Dict[str, Any], path: str = "outputs/house_identity.json") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(identity, file_handle, indent=2)
    return path