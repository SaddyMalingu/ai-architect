#!/usr/bin/env python3
"""
Automated UI/backend integration test script for AI Architect Cloud Studio.
Runs the main render flow (single view and all views), history load, and checks for errors in the API responses.

Requirements:
- requests
- Python 3.8+
- Set environment variables or edit config below for your deployment.
"""
import os
import sys
import time
import requests

# --- Config ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://eccvtkqkllegzbypaemw.supabase.co")
ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVjY3Z0a3FrbGxlZ3pieXBhZW13Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyNTcxODcsImV4cCI6MjA5MTgzMzE4N30.F6ylVSRrYjOlOSZBYEBmuwpfrxBbeF74DImUNSspIgY")
USER_ID = os.getenv("SUPABASE_USER_ID", "ec470708-d89c-4575-9d94-b57cd681bb8b")

HEADERS = {
    "Content-Type": "application/json",
    "apikey": ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}"
}

RENDER_PROMPT = "Modern 2-storey facade, warm evening lighting"
RENDER_STYLE = "photoreal exterior"
MODEL = "black-forest-labs/flux-2-pro"


def check_response(resp, context):
    try:
        data = resp.json()
    except Exception:
        print(f"[FAIL] {context}: Non-JSON response: {resp.text}")
        return False
    if not resp.ok:
        print(f"[FAIL] {context}: HTTP {resp.status_code} - {data}")
        return False
    if 'error' in data and data['error']:
        print(f"[FAIL] {context}: API error: {data['error']}")
        return False
    print(f"[OK] {context}")
    return data


def run_single_render():
    url = f"{SUPABASE_URL}/functions/v1/render"
    payload = {
        "user_id": USER_ID,
        "prompt": RENDER_PROMPT,
        "style": RENDER_STYLE,
        "model": MODEL,
        "num_outputs": 1
    }
    print(f"[INFO] Running single render: {url}")
    resp = requests.post(url, headers=HEADERS, json=payload)
    data = check_response(resp, "single render")
    if not data or 'request_id' not in data:
        print("[FAIL] No request_id returned.")
        return None
    return data['request_id']


def poll_status(request_id, max_wait=60):
    url = f"{SUPABASE_URL}/functions/v1/render-status?request_id={request_id}&user_id={USER_ID}"
    print(f"[INFO] Polling status for request_id={request_id}")
    for _ in range(max_wait // 2):
        resp = requests.get(url, headers=HEADERS)
        data = check_response(resp, "status poll")
        if not data:
            return False
        if data.get('status') in ("completed", "failed", "canceled"):
            print(f"[INFO] Final status: {data['status']}")
            return data['status'] == "completed"
        time.sleep(2)
    print("[FAIL] Polling timed out.")
    return False


def run_all_views():
    views = ["front", "left", "right", "back"]
    results = {}
    for view in views:
        print(f"[INFO] Rendering view: {view}")
        url = f"{SUPABASE_URL}/functions/v1/render"
        payload = {
            "user_id": USER_ID,
            "prompt": f"{RENDER_PROMPT}. camera view: {view}",
            "style": RENDER_STYLE,
            "model": MODEL,
            "num_outputs": 1
        }
        resp = requests.post(url, headers=HEADERS, json=payload)
        data = check_response(resp, f"render {view}")
        if not data or 'request_id' not in data:
            results[view] = False
            continue
        ok = poll_status(data['request_id'])
        results[view] = ok
    return results


def load_history():
    url = f"{SUPABASE_URL}/functions/v1/render-history?user_id={USER_ID}&limit=5&offset=0"
    print(f"[INFO] Loading history: {url}")
    resp = requests.get(url, headers=HEADERS)
    data = check_response(resp, "load history")
    if not data:
        return False
    items = data.get('items', [])
    print(f"[INFO] History items: {len(items)}")
    return True


def main():
    print("[RUN] Automated integration test: single render")
    req_id = run_single_render()
    if req_id:
        poll_status(req_id)
    print("[RUN] Automated integration test: all views")
    results = run_all_views()
    print(f"[RESULTS] All views: {results}")
    print("[RUN] Automated integration test: load history")
    load_history()

if __name__ == "__main__":
    main()
