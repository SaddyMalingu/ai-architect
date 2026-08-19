#!/usr/bin/env python3
"""Fetch production artifacts and Replicate prediction statuses.

Usage examples:
  # fetch prediction statuses (env REPLICATE_API_TOKEN or --token)
  python scripts/fetch_prod_logs.py --prediction-ids id1,id2,id3

  # download a manifest by URL and fetch predictions referenced in it
  python scripts/fetch_prod_logs.py --manifest-url "https://.../manifest.json" --download-manifest

This script intentionally avoids requiring Supabase service keys; instead it
accepts manifest URLs (signed or public) or Replicate tokens/IDs which you can
provide temporarily. For Supabase function logs or storage access, see the
README instructions to produce signed URLs or use the Supabase CLI.
"""
import argparse
import json
import os
import sys
import time
from typing import List, Optional

import requests


OUT_DIR = "logs/production"


def ensure_out_dir():
    os.makedirs(OUT_DIR, exist_ok=True)


def fetch_manifest(manifest_url: str, out_path: Optional[str] = None) -> Optional[dict]:
    out_path = out_path or os.path.join(OUT_DIR, "manifest.json")
    try:
        resp = requests.get(manifest_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Saved manifest to {out_path}")
        return data
    except Exception as e:
        print(f"Failed to fetch manifest from {manifest_url}: {e}")
        return None


def fetch_replicate_prediction(pred_id: str, token: str) -> Optional[dict]:
    url = f"https://api.replicate.com/v1/predictions/{pred_id}"
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        out_file = os.path.join(OUT_DIR, f"replicate_prediction_{pred_id}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Saved Replicate prediction {pred_id} -> {out_file}")
        return data
    except Exception as e:
        print(f"Failed to fetch Replicate prediction {pred_id}: {e}")
        return None


def main(argv: List[str]):
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-ids", help="Comma-separated replicate prediction ids")
    parser.add_argument("--token", help="Replicate API token (or set REPLICATE_API_TOKEN env var)")
    parser.add_argument("--manifest-url", help="URL to outputs/manifest.json (public or signed)")
    parser.add_argument("--download-manifest", action="store_true", help="Download manifest when manifest-url provided")
    args = parser.parse_args(argv)

    ensure_out_dir()

    rep_token = args.token or os.getenv("REPLICATE_API_TOKEN")

    pred_ids: List[str] = []
    if args.prediction_ids:
        pred_ids = [p.strip() for p in args.prediction_ids.split(",") if p.strip()]

    manifest = None
    if args.manifest_url and args.download_manifest:
        manifest = fetch_manifest(args.manifest_url)

    # optionally extract prediction IDs from manifest if present
    if manifest and isinstance(manifest, dict):
        # look for common fields that might reference replicate prediction ids
        # e.g., manifest['renders'] may include objects with 'prediction_id'
        found = []
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, str) and v.startswith("pred_"):
                        found.append(v)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for item in o:
                    walk(item)
        walk(manifest)
        if found:
            print(f"Extracted {len(found)} prediction ids from manifest")
            pred_ids.extend(found)

    pred_ids = list(dict.fromkeys(pred_ids))  # dedupe preserving order

    if pred_ids and not rep_token:
        print("Prediction IDs were provided but no Replicate token found. Set REPLICATE_API_TOKEN or pass --token.")

    for pid in pred_ids:
        if not rep_token:
            break
        fetch_replicate_prediction(pid, rep_token)
        time.sleep(0.2)

    if not pred_ids and not manifest:
        print("Nothing to fetch. Provide --prediction-ids or --manifest-url --download-manifest.")


if __name__ == "__main__":
    main(sys.argv[1:])
