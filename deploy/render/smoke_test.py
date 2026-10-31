"""End-to-end smoke test for a deployed HeritageLens (stdlib only).

    python deploy/render/smoke_test.py --api https://heritagelens-hc26.onrender.com \
        --web https://heritagelens-hc26.vercel.app [--upload]

Waits out a free-tier cold start, then exercises every public read endpoint, cross-script search, the
SSE stream and worker auth. `--web` also checks the Next.js pages and its `/api` proxy. `--upload` sends a
short field note through the ingest pipeline (extract -> index on the CPU queue) and searches for it.
Exits non-zero on the first failed check.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

UA = {"User-Agent": "heritagelens-smoke/1.0"}
QUERIES = ("stepwell", "rani ki vav", "વાવ", "बावड़ी", "रानी की वाव")


class Smoke:
    def __init__(self, api: str, timeout: float) -> None:
        self.api = api.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.passed = 0

    def ok(self, label: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  ok  {label}{'  ' + detail if detail else ''}")

    def fail(self, label: str, detail: str) -> None:
        print(f"  FAIL {label}: {detail}")
        sys.exit(1)

    def request(
        self, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        # GETs retry: free-tier proxies occasionally cut a large body short.
        for attempt in range(3):
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
            except urllib.error.HTTPError as e:
                return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
            except (http.client.IncompleteRead, ConnectionError, TimeoutError, urllib.error.URLError) as e:
                if attempt == 2 or data is not None:
                    raise
                print(f"  ..  retrying {url} after {type(e).__name__}")
                time.sleep(2)
        raise AssertionError("unreachable")

    def get_json(self, path: str, label: str) -> Any:
        status, _, body = self.request(self.api + path)
        if status != 200:
            self.fail(label, f"HTTP {status} {body[:200]!r}")
        return json.loads(body)

    def get_bytes(self, path: str, label: str, mime_prefix: str = "") -> bytes:
        status, headers, body = self.request(self.api + path)
        ctype = headers.get("content-type", "")
        if status != 200 or not body or not ctype.startswith(mime_prefix):
            self.fail(label, f"HTTP {status}, {len(body)} bytes, content-type {ctype!r}")
        self.ok(label, f"{len(body) / 1024:.0f} KB {ctype.split(';')[0]}")
        return body

    # ---------------------------------------------------------------- checks
    def wait_healthy(self, budget: float) -> None:
        t0 = time.monotonic()
        while True:
            try:
                status, _, body = self.request(self.api + "/health")
                if status == 200 and json.loads(body).get("status") == "ok":
                    self.ok("health", f"after {time.monotonic() - t0:.0f}s")
                    return
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
            if time.monotonic() - t0 > budget:
                self.fail("health", f"not healthy within {budget:.0f}s")
            time.sleep(5)

    def ops(self) -> None:
        ready = self.get_json("/ready", "ready")
        if ready["status"] != "ok":
            self.fail("ready", json.dumps(ready))
        self.ok("ready", f"embedder={ready['embedder']} db={ready['database']}")
        stats = self.get_json("/stats", "stats")
        for key in ("assets", "sites", "journeys", "chunks", "twins"):
            if not stats[key]:
                self.fail("stats", f"{key} is 0")
        self.ok(
            "stats",
            f"{stats['assets']} assets, {stats['sites']} sites, {stats['journeys']} journeys, "
            f"{stats['chunks']} chunks, {stats['twins']} twins, languages={sorted(stats['languages'])}",
        )
        self.get_json("/jobs?limit=5", "jobs")
        self.ok("jobs")
        workers = self.get_json("/workers", "workers")
        self.ok("workers", f"{len(workers)} registered")

    def catalogue(self) -> None:
        sites = self.get_json("/sites", "sites")
        site = self.get_json("/sites/rani-ki-vav", "site detail")
        self.ok("sites", f"{len(sites)} sites; rani-ki-vav has {len(site.get('assets', []))} assets")
        geo = self.get_json("/sites/geojson", "sites geojson")
        self.ok("sites geojson", f"{len(geo['features'])} features")

        journeys = self.get_json("/journeys", "journeys")
        if not journeys:
            self.fail("journeys", "empty")
        detail = self.get_json(f"/journeys/{journeys[0]['slug']}", "journey detail")
        self.ok("journeys", f"{len(journeys)} journeys; '{detail['title']}' has {len(detail['stops'])} stops")
        self.get_json("/journeys/geojson", "journeys geojson")
        self.ok("journeys geojson")

        page = self.get_json("/assets?limit=50", "assets")
        items = page["items"]
        if not items:
            self.fail("assets", "empty")
        self.ok("assets", f"{page['total']} total")
        doc = next((a for a in items if a["kind"] in ("journal", "pdf", "story", "scan")), items[0])
        self.get_json(f"/assets/{doc['id']}", "asset detail")
        chunks = self.get_json(f"/assets/{doc['id']}/chunks", "chunks")
        self.ok("asset detail + chunks", f"#{doc['id']} '{doc['title']}' -> {len(chunks)} passages")
        self.get_json("/assets/geojson", "assets geojson")
        self.ok("assets geojson")
        photo = next((a for a in items if a["kind"] in ("photo", "scan")), None)
        if photo:
            self.get_bytes(f"/assets/{photo['id']}/thumbnail", "thumbnail", "image/")
            self.get_bytes(f"/assets/{photo['id']}/original", "original")

        twins = self.get_json("/twins", "twins")
        if not twins:
            self.fail("twins", "empty")
        self.ok("twins", ", ".join(sorted({t["format"] for t in twins})) + f" ({len(twins)})")
        self.get_bytes(f"/twins/{twins[0]['id']}/file", "twin file")

    def search(self) -> None:
        for q in QUERIES:
            t0 = time.monotonic()
            res = self.get_json("/search?" + urllib.parse.urlencode({"q": q, "limit": 5}), f"search {q!r}")
            took = time.monotonic() - t0
            if not res["total"]:
                self.fail(f"search {q!r}", "no results")
            top = res["hits"][0]["asset"]["title"] if res.get("hits") else "-"
            self.ok(f"search {q!r}", f"{res['total']} hits in {took:.2f}s ({res['took_ms']:.0f} ms server), top: {top}")

    def sse(self) -> None:
        req = urllib.request.Request(self.api + "/events", headers={**UA, "Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            ctype = r.headers.get("content-type", "")
            first = r.readline().decode()
        if not ctype.startswith("text/event-stream") or not first.startswith("retry:"):
            self.fail("events (SSE)", f"content-type {ctype!r}, first line {first!r}")
        self.ok("events (SSE)", first.strip())

    def worker_auth(self) -> None:
        body = json.dumps({"name": "smoke", "queue": "gpu", "capabilities": []}).encode()
        status, _, _ = self.request(
            self.api + "/workers/register",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer wrong-token"},
        )
        if status not in (401, 403):
            self.fail("worker auth", f"bad token got HTTP {status}")
        self.ok("worker auth", f"bad token rejected ({status})")

    def upload(self) -> None:
        tag = uuid.uuid4().hex[:8]
        note = (
            f"Smoke test field note {tag}. Visited the Adalaj stepwell near Gandhinagar; the five-storey vav "
            "has carved pillars, a Solanki-style octagonal well and an inscription from 1499.\n"
            "અડાલજની વાવ ગાંધીનગર પાસે આવેલી છે."
        )
        boundary = uuid.uuid4().hex
        parts = [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="smoke-{tag}.txt"\r\n'
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            ).encode()
            + note.encode()
            + b"\r\n",
            f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nSmoke test note {tag}\r\n'.encode(),
            f"--{boundary}--\r\n".encode(),
        ]
        status, _, body = self.request(
            self.api + "/assets",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        if status != 201:
            self.fail("upload", f"HTTP {status} {body[:300]!r}")
        asset_id = json.loads(body)[0]["asset"]["id"]
        t0 = time.monotonic()
        while time.monotonic() - t0 < 180:
            asset = self.get_json(f"/assets/{asset_id}", "uploaded asset")
            if asset["status"] in ("ready", "failed"):
                break
            time.sleep(3)
        if asset["status"] != "ready":
            self.fail("upload", f"asset #{asset_id} status {asset['status']}: {asset.get('error')}")
        self.ok("upload + pipeline", f"#{asset_id} ready in {time.monotonic() - t0:.0f}s")
        res = self.get_json("/search?" + urllib.parse.urlencode({"q": tag}), "search uploaded")
        if not any(h["asset"]["id"] == asset_id for h in res["hits"]):
            self.fail("search uploaded", f"#{asset_id} not found for {tag!r}")
        self.ok("search uploaded", f"found #{asset_id}")


def check_web(smoke: Smoke, web: str) -> None:
    web = web.rstrip("/")
    for path in ("/", "/sites", "/sites/rani-ki-vav", "/journeys", "/search?q=vav", "/archive", "/contribute"):
        status, _, body = smoke.request(web + path)
        if status != 200 or b"HeritageLens" not in body:
            smoke.fail(f"web {path}", f"HTTP {status}, {len(body)} bytes")
        smoke.ok(f"web {path}", f"{len(body) / 1024:.0f} KB")
    status, _, body = smoke.request(web + "/api/v1/stats")
    if status != 200 or not json.loads(body).get("assets"):
        smoke.fail("web /api proxy", f"HTTP {status} {body[:200]!r}")
    smoke.ok("web /api proxy", "stats via rewrite")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", required=True, help="API origin, e.g. https://heritagelens-hc26.onrender.com")
    p.add_argument("--web", help="web origin, e.g. https://heritagelens-hc26.vercel.app")
    p.add_argument("--upload", action="store_true", help="also ingest a small field note")
    p.add_argument("--cold-start", type=float, default=240, help="seconds to wait for /health")
    p.add_argument("--timeout", type=float, default=120, help="per-request timeout")
    args = p.parse_args()

    smoke = Smoke(args.api, args.timeout)
    print(f"API {smoke.api}")
    smoke.wait_healthy(args.cold_start)
    smoke.ops()
    smoke.catalogue()
    smoke.search()
    smoke.sse()
    smoke.worker_auth()
    if args.upload:
        smoke.upload()
    if args.web:
        print(f"WEB {args.web}")
        check_web(smoke, args.web)
    print(f"all {smoke.passed} checks passed")


if __name__ == "__main__":
    main()
