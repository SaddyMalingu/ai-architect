#!/usr/bin/env python3
"""
Automated integration test: regional edit flow for AI Architect Cloud Studio.
Runs a regional edit and checks for errors in the API responses.

Requirements:
- requests
- Python 3.8+
- Set environment variables or edit config below for your deployment.
"""
import os
import sys
import time
import requests

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://eccvtkqkllegzbypaemw.supabase.co")
ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVjY3Z0a3FrbGxlZ3pieXBhZW13Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyNTcxODcsImV4cCI6MjA5MTgzMzE4N30.F6ylVSRrYjOlOSZBYEBmuwpfrxBbeF74DImUNSspIgY")
USER_ID = os.getenv("SUPABASE_USER_ID", "ec470708-d89c-4575-9d94-b57cd681bb8b")

HEADERS = {
    "Content-Type": "application/json",
    "apikey": ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}"
}

EDIT_PROMPT = "Apply warm wood facade texture to selected area"
EDIT_CATEGORY = "element_texture"
REGION_HINT = "facade"
MODEL_PROFILE = "balanced"
STRENGTH = 0.65

# Use a valid image URL from your storage or a placeholder
TARGET_IMAGE_URL = os.getenv("TARGET_IMAGE_URL", "https://placehold.co/512x384.png")


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


def run_regional_edit():
    url = f"{SUPABASE_URL}/functions/v1/edit-regional"
    payload = {
        "user_id": USER_ID,
        "target_image_url": TARGET_IMAGE_URL,
        "prompt": EDIT_PROMPT,
        "edit_category": EDIT_CATEGORY,
        "region_hint": REGION_HINT,
        "selection_mode": "automatic",
        "model_profile": MODEL_PROFILE,
        "strength": STRENGTH
    }
    print(f"[INFO] Running regional edit: {url}")
    resp = requests.post(url, headers=HEADERS, json=payload)
    data = check_response(resp, "regional edit")
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


def main():
    print("[RUN] Automated integration test: regional edit")
    req_id = run_regional_edit()
    if req_id:
        poll_status(req_id)

if __name__ == "__main__":
    main()
