import json
import os
import re
from typing import Any, Dict, Optional

import requests

DEFAULT_MODEL_ID = "meta-llama/Llama-3.1-8B-Instruct:novita"
HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    # find first JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def generate_specs_with_hf(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")
    if not api_key:
        return None

    model_id = os.getenv("HF_MODEL_ID", DEFAULT_MODEL_ID)
    url = os.getenv("HF_BASE_URL", HF_ROUTER_URL)

    system_msg = (
        "You are an architecture planning assistant. Return ONLY a JSON object that matches the schema, no prose."
    )
    schema = {
        "style": "modern|classic|contemporary|minimal|rustic",
        "floors": 1,
        "bedrooms": 3,
        "bathrooms": 2,
        "roof_type": "gable|hip|flat",
        "porch": True,
        "garage": True,
        "dormer": False,
        "materials": {
            "wall": "stucco|brick|wood",
            "roof": "shingle|metal|tile",
            "trim": "white|black|wood",
            "window": "clear|tinted"
        },
        "window_pattern": "symmetrical|asymmetrical",
        "site": {
            "driveway": True,
            "trees": 2
        },
        "facades": {
            "comment": "Optional facade family definitions for asymmetric designs",
            "gable_facade": "front|rear (which elevation has visual emphasis)",
            "secondary_volume_side": "left|right (which side has secondary massing)",
            "front_dominant": True,
            "entry_offset": 0.0
        }
    }

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": (
                    f"Architecture Planning Schema:\n{json.dumps(schema, indent=2)}\n\n"
                    f"For the given prompt, propose:\n"
                    f"- Basic design parameters (style, floors, porch, garage, dormer)\n"
                    f"- Material selection (wall, roof, trim, window)\n"
                    f"- Facade strategy: which elevation should be prominent, where should secondary volume be, "
                    f"asymmetric entry offset if desired\n"
                    f"- Site features (driveway, trees)\n\n"
                    f"Prompt: {prompt}\n\n"
                    f"Return ONLY valid JSON matching the schema."
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 500,
    }

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        text = ""
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                text = message.get("content", "")
        return normalize_specs(_extract_json(text))
    except Exception:
        return None


def normalize_specs(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None

    def pick_enum(value, allowed, default):
        if not value:
            return default
        v = str(value).lower()
        for a in allowed:
            if a in v:
                return a
        return default

    specs = {
        "style": pick_enum(raw.get("style"), ["modern", "classic", "contemporary", "minimal", "rustic"], "modern"),
        "floors": int(raw.get("floors", 1) or 1),
        "bedrooms": int(raw.get("bedrooms", 3) or 3),
        "bathrooms": int(raw.get("bathrooms", 2) or 2),
        "roof_type": pick_enum(raw.get("roof_type"), ["gable", "hip", "flat"], "gable"),
        "porch": bool(raw.get("porch", True)),
        "garage": bool(raw.get("garage", True)),
        "dormer": bool(raw.get("dormer", False)),
        "window_pattern": pick_enum(raw.get("window_pattern"), ["symmetrical", "asymmetrical"], "symmetrical"),
        "materials": {
            "wall": pick_enum(raw.get("materials", {}).get("wall"), ["stucco", "brick", "wood"], "stucco"),
            "roof": pick_enum(raw.get("materials", {}).get("roof"), ["shingle", "metal", "tile"], "shingle"),
            "trim": pick_enum(raw.get("materials", {}).get("trim"), ["white", "black", "wood"], "white"),
            "window": pick_enum(raw.get("materials", {}).get("window"), ["clear", "tinted"], "clear"),
        },
        "site": {
            "driveway": bool(raw.get("site", {}).get("driveway", True)),
            "trees": int(raw.get("site", {}).get("trees", 2) or 0),
        },
        "facades": {
            "gable_facade": pick_enum(raw.get("facades", {}).get("gable_facade"), ["front", "rear"], "front"),
            "secondary_volume_side": pick_enum(raw.get("facades", {}).get("secondary_volume_side"), ["left", "right"], "left"),
            "front_dominant": bool(raw.get("facades", {}).get("front_dominant", True)),
            "entry_offset": float(raw.get("facades", {}).get("entry_offset", 0.0) or 0.0),
        },
    }
    return specs
