#!/usr/bin/env python3
"""Download public render images and compute per-image stats and group SSIM.

Usage: python scripts/perceptual_check.py --history scripts/prod_render_history.json --out scripts/perceptual_report.json
"""
import argparse
import json
import os
import re
import sys
from io import BytesIO

import numpy as np
from PIL import Image
import requests
from skimage.metrics import structural_similarity as ssim
from skimage.color import rgb2gray


def download_image(url, timeout=30, retries=4, backoff=1.5):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB"), len(r.content)
        except Exception as e:
            last_exc = e
            wait = backoff ** (attempt - 1)
            print(f"download failed (attempt {attempt}/{retries}) for {url}: {e}; retrying in {wait:.1f}s")
            try:
                import time

                time.sleep(wait)
            except Exception:
                pass
    # final failure
    raise last_exc


def img_stats(img):
    a = np.array(img).astype(np.float32) / 255.0
    gray = rgb2gray(a)
    mean = float(gray.mean())
    std = float(gray.std())
    # Laplacian variance (sharpness proxy)
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    lap_var = float((gx.var() + gy.var()) / 2.0)
    return {"w": img.width, "h": img.height, "mean_lum": mean, "std_lum": std, "lap_var": lap_var}


def compute_ssim(img1, img2):
    # convert to grayscale and resize to same shape
    a = np.array(img1.convert("L")).astype(np.float32) / 255.0
    b = np.array(img2.convert("L")).astype(np.float32) / 255.0
    if a.shape != b.shape:
        # resize b to a
        b_img = Image.fromarray((b * 255).astype(np.uint8))
        b_img = b_img.resize((a.shape[1], a.shape[0]), Image.LANCZOS)
        b = np.array(b_img).astype(np.float32) / 255.0
    score = float(ssim(a, b, data_range=1.0))
    return score


def extract_house_token(prompt):
    m = re.search(r"bp3-house-[a-z0-9-]+", prompt)
    return m.group(0) if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--history", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=200)
    args = p.parse_args()

    with open(args.history, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])[: args.limit]
    os.makedirs("tmp/perceptual", exist_ok=True)

    results = []
    groups = {}

    for it in items:
        url = it.get("image_url")
        rid = it.get("request_id")
        prompt = it.get("prompt", "")
        try:
            img, size = download_image(url)
        except Exception as e:
            results.append({"request_id": rid, "error": str(e), "image_url": url})
            continue

        stats = img_stats(img)
        stats.update({"request_id": rid, "image_url": url, "bytes": size, "prompt": prompt, "created_at": it.get("created_at")})
        results.append(stats)

        token = extract_house_token(prompt)
        if token:
            groups.setdefault(token, []).append((rid, img, it.get("created_at")))

    # compute SSIM within groups (earliest as reference)
    group_ssim = {}
    for token, arr in groups.items():
        # sort by created_at
        arr_sorted = sorted(arr, key=lambda x: x[2] or "")
        ref_id, ref_img, _ = arr_sorted[0]
        scores = []
        for rid, img, _ in arr_sorted[1:]:
            try:
                score = compute_ssim(ref_img, img)
            except Exception:
                score = None
            scores.append({"request_id": rid, "ssim_to_ref": score})
        group_ssim[token] = {"ref_request_id": ref_id, "comparisons": scores}

    out = {"summary_count": len(results), "items": results, "group_ssim": group_ssim}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote report to {args.out}. Images processed: {len(results)}. Groups: {len(group_ssim)}")


if __name__ == "__main__":
    main()
