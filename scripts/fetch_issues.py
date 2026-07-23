#!/usr/bin/env python3
"""Fetch resolved Okdesk issues for the last N months into data/."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LIST_PATH = DATA / "issues_list.jsonl"
DETAILS_DIR = DATA / "issues"
META_PATH = DATA / "fetch_meta.json"

PAGE_SIZE = 50
MAX_WORKERS = 8
RETRIES = 4


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # OS env wins
    for k in ("OKDESK_DOMAIN", "OKDESK_API_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if not env.get("OKDESK_DOMAIN") or not env.get("OKDESK_API_TOKEN"):
        sys.exit("Missing OKDESK_DOMAIN or OKDESK_API_TOKEN in .env")
    env["OKDESK_DOMAIN"] = env["OKDESK_DOMAIN"].rstrip("/")
    return env


def api_get(base: str, path: str, token: str, params: list[tuple[str, str]]) -> object:
    q = [("api_token", token), *params]
    url = f"{base}/api/v1{path}?{urllib.parse.urlencode(q)}"
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"HTTP {e.code}: {body[:500]}")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_err from e
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed GET {path}: {last_err}")


def period_bounds(months: int = 6) -> tuple[str, str]:
    # Okdesk expects DD-MM-YYYY HH:MM
    until = datetime.now()
    since = until - timedelta(days=30 * months)
    return since.strftime("%d-%m-%Y 00:00"), until.strftime("%d-%m-%Y 23:59")


def fetch_list(env: dict[str, str], since: str, until: str) -> list[dict]:
    token = env["OKDESK_API_TOKEN"]
    base = env["OKDESK_DOMAIN"]
    rows: list[dict] = []
    page = 1
    while True:
        params = [
            ("page[size]", str(PAGE_SIZE)),
            ("page[number]", str(page)),
            ("completed_since", since),
            ("completed_until", until),
            ("status_codes[]", "completed"),
            ("status_codes[]", "closed"),
            ("sorting[field]", "created_at"),
            ("sorting[direction]", "forward"),
        ]
        batch = api_get(base, "/issues/list", token, params)
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected list response: {type(batch)}")
        if not batch:
            break
        rows.extend(batch)
        print(f"list page {page}: +{len(batch)} (total {len(rows)})", flush=True)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.15)
    return rows


def save_list(rows: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with LIST_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_list() -> list[dict]:
    if not LIST_PATH.exists():
        return []
    return [json.loads(line) for line in LIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def fetch_detail(env: dict[str, str], issue_id: int) -> dict:
    path = DETAILS_DIR / f"{issue_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    token = env["OKDESK_API_TOKEN"]
    base = env["OKDESK_DOMAIN"]
    detail = api_get(base, f"/issues/{issue_id}", token, [])
    path.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return detail  # type: ignore[return-value]


def fetch_details(env: dict[str, str], ids: list[int]) -> None:
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    pending = [i for i in ids if not (DETAILS_DIR / f"{i}.json").exists()]
    done = len(ids) - len(pending)
    print(f"details cached={done} pending={len(pending)}", flush=True)
    if not pending:
        return

    ok = 0
    fail = 0

    def one(i: int) -> tuple[int, bool, str]:
        try:
            fetch_detail(env, i)
            return i, True, ""
        except Exception as e:  # noqa: BLE001
            return i, False, str(e)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(one, i) for i in pending]
        for n, fut in enumerate(as_completed(futs), 1):
            _id, success, err = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
                print(f"FAIL {_id}: {err}", flush=True)
            if n % 50 == 0 or n == len(futs):
                print(f"details progress {n}/{len(futs)} ok={ok} fail={fail}", flush=True)


def main() -> None:
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    env = load_env()
    since, until = period_bounds(months)
    print(f"period {since} .. {until}", flush=True)

    if "--details-only" in sys.argv:
        rows = load_list()
        if not rows:
            sys.exit("No issues_list.jsonl — run without --details-only first")
    else:
        rows = fetch_list(env, since, until)
        save_list(rows)
        META_PATH.write_text(
            json.dumps(
                {
                    "since": since,
                    "until": until,
                    "months": months,
                    "list_count": len(rows),
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"saved list: {len(rows)} -> {LIST_PATH}", flush=True)

    ids = sorted({int(r["id"]) for r in rows})
    fetch_details(env, ids)
    print("done", flush=True)


if __name__ == "__main__":
    main()
