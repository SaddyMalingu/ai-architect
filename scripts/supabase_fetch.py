#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
import urllib.parse
import ssl

def read_token(path="scripts/_sb_token.txt"):
    if not os.path.exists(path):
        print("Token file not found:", path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _fetch_json(url, token, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"Bearer {token}", "apikey": token}
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = resp.read()
        return json.loads(data.decode("utf-8"))


def list_buckets(base_url, token):
    url = f"{base_url}/storage/v1/buckets"
    return _fetch_json(url, token)


def list_objects(base_url, token, bucket, prefix="", limit=100):
    url = f"{base_url}/storage/v1/object/list/{bucket}"
    params = {"prefix": prefix, "limit": limit}
    return _fetch_json(url, token, params=params)


def download_object(base_url, token, bucket, path, out_path):
    url = f"{base_url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        data = resp.read()
        with open(out_path, "wb") as f:
            f.write(data)
    return out_path


def main():
    project = os.getenv("SB_PROJECT") or "eccvtkqkllegzbypaemw"
    base_url = f"https://{project}.supabase.co"
    token = read_token()

    print("Listing buckets...")
    try:
        buckets = list_buckets(base_url, token)
        print(json.dumps(buckets, indent=2)[:2000])
    except Exception as e:
        print("Failed to list buckets:", e)
        return

    # try common buckets
    for b in buckets:
        name = b.get("name")
        if not name:
            continue
        # look for outputs prefix
        try:
            objs = list_objects(base_url, token, name, prefix="outputs", limit=50)
            if objs:
                print(f"Objects in bucket {name} with prefix 'outputs': {len(objs)} entries")
                print(json.dumps(objs, indent=2)[:3000])
        except Exception:
            pass

    # try known bucket names
    for candidate in ["renders", "public", "outputs", "studio-outputs"]:
        try:
            objs = list_objects(base_url, token, candidate, prefix="", limit=50)
            if objs:
                print(f"Found objects in {candidate}: {len(objs)}")
                print(json.dumps(objs, indent=2)[:3000])
        except Exception:
            pass


def diagnose():
    project = os.getenv("SB_PROJECT") or "eccvtkqkllegzbypaemw"
    base_url = f"https://{project}.supabase.co"
    token = read_token()
    headers = {"Authorization": f"Bearer {token}", "apikey": token}
    endpoints = [
        f"{base_url}/storage/v1",
        f"{base_url}/storage/v1/buckets",
        f"{base_url}/rest/v1/",
        f"{base_url}/functions/v1",
    ]
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    for ep in endpoints:
        req = urllib.request.Request(ep, headers=headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                print(f"{ep} -> {resp.status}")
        except Exception as e:
            print(f"{ep} -> ERROR: {e}")


def fetch_table(base_url, token, table, limit=10):
    # Supabase REST: /rest/v1/<table>?select=*&order=created_at.desc&limit=10
    params = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    url = f"{base_url}/rest/v1/{table}"
    try:
        data = _fetch_json(url, token, params=params)
        print(f"Fetched {len(data)} rows from {table}")
        print(json.dumps(data, indent=2)[:8000])
        return data
    except Exception as e:
        print(f"Failed to fetch table {table}: {e}")
        return None



if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        diagnose()
    else:
        main()


if __name__ == "__main__":
    main()
