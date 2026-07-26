"""Flag Error: turn a user's report into a GitHub issue.

Carmine hits "Flag Error" in the app, types what looks wrong, and the client
posts the description plus a PNG of the chart panels and the diagnostics the
app already holds (version, file, provider, chart/stage, PDF page, extraction
notes, per-channel axis ranges). This opens an issue on the repo so the
reports land in one monitored inbox instead of an email thread.

The screenshot is committed to reports/ first, then embedded in the issue
body — the issues API has no attachment endpoint, but an image committed to
the repo renders inline from its raw URL.

Server env (set in Vercel, never shipped in the EXE):
  FLAG_GITHUB_TOKEN  PAT with `repo` scope on FLAG_REPO
  FLAG_REPO          owner/name, default chrispyscripts/frac2csv
  FLAG_BRANCH        branch the screenshots are committed to, default
                     "reports". Keeping them OFF main matters: every report
                     is a commit, so writing to main means the working branch
                     gains a commit per report and local pushes start getting
                     rejected until you pull.
  FLAG_APP_KEY       optional shared string the client must send. This is a
                     speed bump against drive-by bots, NOT authentication —
                     anything shipped in a desktop binary is readable.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

GH_API = "https://api.github.com"
REPO = os.environ.get("FLAG_REPO", "chrispyscripts/frac2csv")
TOKEN = os.environ.get("FLAG_GITHUB_TOKEN", "")
APP_KEY = os.environ.get("FLAG_APP_KEY", "")
BRANCH = os.environ.get("FLAG_BRANCH", "reports")

MAX_BODY = 4_000_000          # Vercel caps the request body around 4.5MB
MAX_SHOT = 3_000_000          # decoded PNG ceiling
MAX_DESC = 4000


def _gh(method, path, payload=None):
    req = urllib.request.Request(
        GH_API + path, method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "frac2csv-flag"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode() or "{}")


def _slug(s, n=60):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s[:n] or "unlabelled"


def _fmt_diag(d):
    """Diagnostics dict -> a readable markdown block. Anything the client
    sends is rendered, so new fields need no server change."""
    if not isinstance(d, dict):
        return ""
    order = ["version", "provider", "file", "chart", "stage", "pdfPage",
             "duration", "samples", "ghost", "userAgent", "platform"]
    lines = []
    for k in order:
        if d.get(k) not in (None, ""):
            lines.append(f"| {k} | {d[k]} |")
    for k in sorted(d):
        if k in order or k in ("channels", "notes"):
            continue
        v = d[k]
        if isinstance(v, (str, int, float, bool)) and str(v) != "":
            lines.append(f"| {k} | {v} |")
    out = ""
    if lines:
        out += "| field | value |\n| --- | --- |\n" + "\n".join(lines) + "\n"
    chans = d.get("channels")
    if isinstance(chans, list) and chans:
        out += "\n**Channels**\n\n| channel | unit | axis | peak |\n"
        out += "| --- | --- | --- | --- |\n"
        for c in chans[:24]:
            if not isinstance(c, dict):
                continue
            ax = c.get("axis") or ""
            out += (f"| {c.get('key','')} | {c.get('unit','')} | {ax} "
                    f"| {c.get('peak','')} |\n")
    notes = d.get("notes")
    if notes:
        text = notes if isinstance(notes, str) else "\n".join(map(str, notes))
        text = text[:4000]
        out += f"\n**Extraction notes**\n\n```\n{text}\n```\n"
    return out


def _ensure_branch():
    """Create the reports branch off the default head if it isn't there yet."""
    try:
        _gh("GET", f"/repos/{REPO}/branches/{BRANCH}")
        return True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return False
    try:
        repo = _gh("GET", f"/repos/{REPO}")
        head = _gh("GET", f"/repos/{REPO}/git/ref/heads/{repo['default_branch']}")
        _gh("POST", f"/repos/{REPO}/git/refs",
            {"ref": f"refs/heads/{BRANCH}", "sha": head["object"]["sha"]})
        return True
    except Exception:
        return False


def status():
    """Lets the client tell "not configured yet" from "broken"."""
    return {"ready": bool(TOKEN), "repo": REPO, "needsKey": bool(APP_KEY)}


def create_report(req):
    """req dict -> (http_code, response dict). Called by the api.extract
    entrypoint: this project builds ONE Vercel function (pyproject pins
    entrypoint = api.extract:handler), so a standalone flag route would
    never be reached."""
    if not TOKEN:
        return 503, {"error": "reporting is not configured "
                              "(FLAG_GITHUB_TOKEN unset)"}
    if APP_KEY and req.get("key") != APP_KEY:
        return 403, {"error": "bad app key"}

    desc = (req.get("description") or "").strip()[:MAX_DESC]
    if not desc:
        return 400, {"error": "please describe the problem"}
    diag = req.get("diagnostics") or {}
    reporter = _slug(req.get("reporter") or "user", 40)

    # screenshot -> a file in the repo (issues have no attachment API)
    shot_md = ""
    shot = req.get("screenshot") or ""
    m = re.match(r"data:image/(png|jpeg);base64,", shot)
    if m:
        ext = "png" if m.group(1) == "png" else "jpg"
        try:
            blob = base64.b64decode(shot.split(",", 1)[1])
        except Exception:
            blob = b""
        if 0 < len(blob) <= MAX_SHOT:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            path = f"reports/{stamp}-{abs(hash(desc)) % 10000:04d}.{ext}"
            try:
                _ensure_branch()
                _gh("PUT", f"/repos/{REPO}/contents/{path}",
                    {"message": f"flag: screenshot for {_slug(desc, 50)}",
                     "content": base64.b64encode(blob).decode(),
                     "branch": BRANCH})
                shot_md = (f"\n![screenshot](https://raw.githubusercontent.com/"
                           f"{REPO}/{BRANCH}/{path})\n")
            except urllib.error.HTTPError as e:
                shot_md = f"\n_(screenshot upload failed: {e.code})_\n"
            except Exception:
                shot_md = "\n_(screenshot upload failed)_\n"

    title = f"[Flag] {_slug(desc)}"
    where = " · ".join(str(diag.get(k)) for k in ("provider", "file", "chart")
                       if diag.get(k))
    body = (f"**Reported by:** {reporter}\n"
            f"{('**Where:** ' + where + chr(10)) if where else ''}"
            f"\n{desc}\n\n---\n\n{_fmt_diag(diag)}{shot_md}")
    try:
        issue = _gh("POST", f"/repos/{REPO}/issues",
                    {"title": title, "body": body, "labels": ["flag"]})
    except urllib.error.HTTPError as e:
        return 502, {"error": f"GitHub {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return 502, {"error": f"{type(e).__name__}: {e}"}
    return 200, {"ok": True, "url": issue.get("html_url"),
                 "number": issue.get("number")}
