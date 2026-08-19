#!/usr/bin/env python3
"""Post local sketch + reference images to the Supabase Edge render function.

Usage:
  python scripts/post_local_render.py --edge-url https://.../render --user-id <uuid> \
    --sketch "C:\path\to\sketch.jpg" --reference "C:\path\to\images.jpg" \
    --prompt "Render prompt" --model_profile balanced

This script encodes files as data URIs and sends `input_image_b64` and
`reference_image_b64` so the Edge Function will upload them and use a
reference-capable model if needed.
"""
import argparse
import base64
import mimetypes
import json
import os
import sys

import requests


def encode_data_uri(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/jpeg"
    with open(path, "rb") as f:
        b = f.read()
    b64 = base64.b64encode(b).decode("ascii")
    return f"data:{mime};base64,{b64}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--edge-url", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--sketch", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--model_profile", default="balanced")
    args = p.parse_args()

    try:
        sketch_uri = encode_data_uri(args.sketch)
        ref_uri = encode_data_uri(args.reference)
    except Exception as e:
        print("Failed to read/encode files:", e, file=sys.stderr)
        sys.exit(2)

    payload = {
        "user_id": args.user_id,
        "prompt": args.prompt,
        "input_image_b64": sketch_uri,
        "reference_image_b64": ref_uri,
        "model_profile": args.model_profile,
    }

    print("Posting to:", args.edge_url)
    try:
        resp = requests.post(args.edge_url, json=payload, timeout=120)
    except Exception as e:
        print("Request failed:", e, file=sys.stderr)
        sys.exit(3)

    try:
        data = resp.json()
    except Exception:
        print("Non-JSON response status", resp.status_code)
        print(resp.text)
        sys.exit(4)

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
