#!/usr/bin/env python3
"""Post local sketch + reference images to the Supabase Edge render function
without external dependencies (uses urllib).

Usage:
  python scripts/post_local_render_no_requests.py --edge-url https://.../render --user-id <uuid> \
    --sketch scripts/inputs/sketch.jpg --reference scripts/inputs/reference.jpg \
    --prompt "Render prompt" --model_profile balanced
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
from urllib import request, error


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
    p.add_argument("--consistency-key", default=None, help="Stable consistency key used to lock geometry across repeated renders")
    p.add_argument("--strict-consistency", action="store_true", default=True, help="Force geometry-preserving behavior for sketch-based renders")
    p.add_argument("--blender-conditioned", action="store_true", default=False, help="Flag that the input image is a Blender geometry pass")
    p.add_argument("--supabase-key", default=None, help="Supabase anon or service role key (optional). If omitted, reads SUPABASE_KEY env var")
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
        "consistency_key": args.consistency_key or args.user_id,
        "strict_consistency": bool(args.strict_consistency),
        "blender_conditioned": bool(args.blender_conditioned),
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(args.edge_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    key = args.supabase_key or os.environ.get("SUPABASE_KEY")
    if key:
        req.add_header("apikey", key)
        req.add_header("Authorization", f"Bearer {key}")

    try:
        with request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            try:
                j = json.loads(body)
                print(json.dumps(j, indent=2))
            except Exception:
                print("Non-JSON response status", resp.status)
                print(body)
                sys.exit(4)
    except error.URLError as e:
        print("Request failed:", e, file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
