#!/usr/bin/env python3
"""Mirror the public report, without publishing the private authoring repository."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.request

ORIGIN = "https://a-share-review-archive.chen4002812.chatgpt.site"
PROJECT = "appgprj_6ac9c64ca5b881919524d1311dd80bb0"
ARTIFACT = "dashboard:d8650926-9515-42c6-a507-4c9979168165"
SNAPSHOT_TAG = re.compile(r'(<script\b[^>]*\bid="data-app-reviewed-snapshot"[^>]*>)(.*?)(</script>)', re.S)


def digest(value):
    return hashlib.sha256(value).hexdigest()


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not (newurl == ORIGIN or newurl.startswith(ORIGIN + "/")):
            raise ValueError("Source redirected away from the public report origin")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(path):
    opener = urllib.request.build_opener(SameOriginRedirect())
    request = urllib.request.Request(ORIGIN + path, headers={"User-Agent": "AsharePublicMirror/1.0", "Cache-Control": "no-cache"})
    with opener.open(request, timeout=45) as response:
        payload = response.read(80 * 1024 * 1024 + 1)
        if len(payload) > 80 * 1024 * 1024:
            raise ValueError("Public asset exceeded the supported mirror size")
        return payload


def normalize_source_html(html_bytes):
    # Cloudflare adds a request-specific challenge script outside the report.
    # Removing only that edge injection avoids pointless commits on every poll.
    html = html_bytes.decode("utf-8")
    def retain_report_script(match):
        script = match[0]
        if "window.__CF$cv$params" in script and "/cdn-cgi/challenge-platform/scripts/jsd/main.js" in script:
            return ""
        return script
    return re.sub(r'<script(?:\s[^>]*)?>.*?</script>', retain_report_script, html, flags=re.S).encode("utf-8")


def read_verified_pair(fetch=download, attempts=3):
    for attempt in range(attempts):
        try:
            html_bytes = fetch("/")
            snapshot_bytes = fetch("/api/snapshot")
            html = html_bytes.decode("utf-8")
            snapshot = json.loads(snapshot_bytes)
            fingerprint = re.findall(r'<meta name="data-app-snapshot-sha256" content="([a-f0-9]{64})">', html)
            if fingerprint != [digest(snapshot_bytes)]:
                raise ValueError("Page and snapshot are different publication versions")
            if f'<meta name="data-app-sites-project" content="{PROJECT}">' not in html or snapshot.get("id") != ARTIFACT:
                raise ValueError("Unexpected source project or artifact")
            queries = snapshot.get("queries")
            if snapshot.get("buildStatus") != "complete" or not isinstance(queries, dict):
                raise ValueError("Source report is not complete")
            dates = [r.get("review_date", "") for r in queries.get("reports", {}).get("rows", [])]
            if not dates or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates) or len(dates) != len(set(dates)):
                raise ValueError("Missing or duplicate historical report dates")
            return normalize_source_html(html_bytes), snapshot_bytes, snapshot
        except Exception as exc:
            if attempt == attempts - 1:
                raise RuntimeError("Public source unavailable or inconsistent; previous mirror retained") from exc
            time.sleep(2 * (attempt + 1))


def make_portable(html_bytes, snapshot_bytes):
    html = html_bytes.decode("utf-8")
    if len(SNAPSHOT_TAG.findall(html)) != 1:
        raise ValueError("Unsupported report bootstrap; refusing to rewrite application code")
    if "script[data-app-snapshot-chunk]" not in html:
        raise ValueError("Unsupported report runtime")
    # Restore the complete inert JSON, as in the Data portable HTML export.
    # Runtime JavaScript and chart code are kept byte-for-byte unchanged.
    data = snapshot_bytes.decode("utf-8").replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = SNAPSHOT_TAG.sub(lambda m: m[1] + data + m[3], html)
    html = re.sub(r'<script\b[^>]*\bdata-app-snapshot-chunk[^>]*>.*?</script>', "", html, flags=re.S)
    html = re.sub(r'<meta\b[^>]*\bname="data-app-(?:snapshot-storage|local-snapshot|build-layout|local-thread|local-reference|local-project)"[^>]*>', "", html)
    if re.search(r'<meta\b[^>]*\bname="data-app-(?:snapshot-storage|local-snapshot)"', html):
        raise ValueError("Mirror still depends on a hosted data endpoint")
    return html.encode("utf-8")


def validate_history(snapshot, previous):
    rows = snapshot["queries"]["reports"]["rows"]
    by_date = {row["review_date"]: row for row in rows}
    if not set(previous.get("reportDates", [])).issubset(by_date):
        raise ValueError("Source dropped history; refusing to replace the previous mirror")
    return sorted(by_date)


def sync(destination, fetch=download):
    destination = Path(destination)
    manifest_path = destination / "mirror-manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    html_bytes, snapshot_bytes, snapshot = read_verified_pair(fetch)
    dates = validate_history(snapshot, previous)
    manifest = {
        "version": 1, "source": ORIGIN, "artifactId": ARTIFACT,
        "sourceHtmlSha256": digest(html_bytes), "snapshotSha256": digest(snapshot_bytes),
        "generatedAt": snapshot.get("generatedAt"), "reportDates": dates,
        "queryCount": len(snapshot["queries"]),
        "rowCount": sum(len(q.get("rows", [])) for q in snapshot["queries"].values()),
    }
    portable = make_portable(html_bytes, snapshot_bytes)
    manifest["mirrorHtmlSha256"] = digest(portable)
    unchanged = manifest == previous and (destination / "index.html").exists() and digest((destination / "index.html").read_bytes()) == digest(portable)
    if unchanged:
        print("Public report unchanged; no deployment needed")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mirror-stage-", dir=destination.parent))
    try:
        (staging / "index.html").write_bytes(portable)
        (staging / "snapshot.json").write_bytes(snapshot_bytes)
        (staging / "mirror-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        (staging / ".nojekyll").touch()
        # Preserve existing archived snapshots and add a content-addressed revision.
        archive = staging / "history"
        if (destination / "history").exists():
            shutil.copytree(destination / "history", archive)
        archive.mkdir(exist_ok=True)
        historical = archive / f"snapshot-{dates[-1]}-{digest(snapshot_bytes)[:16]}.json"
        if not historical.exists():
            historical.write_bytes(snapshot_bytes)
        backup = destination.with_name(destination.name + ".previous")
        if backup.exists():
            raise ValueError("A previous replacement requires inspection before continuing")
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except Exception:
            if backup.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f"Mirror ready: {len(dates)} reports, {manifest['rowCount']} rows; latest {dates[-1]}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs")
    args = parser.parse_args()
    changed = sync(args.output)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("changed=" + str(changed).lower() + "\n")
