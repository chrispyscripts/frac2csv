"""BC eLibrary integration for the web app.

- list_wellfiles(wa): anonymous — filenames from the public BIL-184 index.
- get_pdf(wa, name): authenticated FTP download, cached in /tmp.
- list_intervals(pdf): chart pages found in the document (IFS or MView).
- extract_interval(...): one stage payload from a chart page.

Credentials: env BCER_FTP_USER / BCER_FTP_PASS (Vercel), falling back to
~/.netrc (local dev). Never logged or returned.
"""
import ftplib
import io
import os
import re
import urllib.request

import fitz

import frac_core as fc
import halliburton_ifs as ifs

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")
INDEX = "https://reports.bc-er.ca/ogc/r/app001/ams_reports/3?IR_ROWFILTER={wa}"
FTP_HOST = "files.bc-er.ca"
CACHE = "/tmp/bcer-cache"


def _creds():
    u = os.environ.get("BCER_FTP_USER")
    p = os.environ.get("BCER_FTP_PASS")
    if u and p:
        return u, p
    netrc_path = os.path.expanduser("~/.netrc")
    if os.path.exists(netrc_path):
        try:
            import netrc
            auth = netrc.netrc(netrc_path).authenticators(FTP_HOST)
            if auth:
                return auth[0], auth[2]
        except Exception:
            pass
    return None, None


def creds_available():
    u, p = _creds()
    return bool(u and p)


def list_wellfiles(wa):
    wa = wa.strip().lstrip("0").zfill(5)
    req = urllib.request.Request(INDEX.format(wa=wa), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    names = sorted(set(re.findall(rf"{wa}_[A-Za-z0-9_.-]+", html)))
    return wa, [n for n in names if "." in n]


def get_pdf(wa, name):
    """Download (or reuse cached) PDF; returns local path."""
    wa = wa.strip().lstrip("0").zfill(5)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", name)
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, f"{wa}-{safe}")
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    user, pw = _creds()
    if not user:
        raise PermissionError("no eLibrary credentials on this server")
    n = int(wa)
    kb = f"{n // 1000 * 1000:05d}-{n // 1000 * 1000 + 999:05d}"
    hb = f"{n // 100 * 100:05d}-{n // 100 * 100 + 99:05d}"
    ftp = ftplib.FTP(FTP_HOST, timeout=45)
    try:
        ftp.login(user, pw)
        ftp.cwd(f"WellData/{kb}/{hb}/{wa}")
        # case-insensitive match against the real listing
        listing = ftp.nlst()
        remote = next((l for l in listing if l.lower() == safe.lower()), safe)
        with open(dest, "wb") as f:
            ftp.retrbinary(f"RETR {remote}", f.write)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    if os.path.getsize(dest) < 1000:
        os.unlink(dest)
        raise FileNotFoundError(f"{name}: empty download")
    return dest


def list_intervals(path):
    """[{page, kind, label}] of extractable chart pages in the document."""
    doc = fitz.open(path)
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        text = page.get_text()
        if "(IFS v" in text:
            m = re.search(r"Interval\s+(\d+)\s*[-–]\s*Entire Treatment", text)
            # a real chart page carries its HH:MM time axis; the table of
            # contents mentions every interval but has no time labels
            if m and len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) >= 3:
                out.append({"page": pno + 1, "kind": "ifs",
                            "label": f"Interval {m.group(1)} — entire treatment"})
            continue
        if fc.page_kind(page) == "vector":
            m = re.search(r"(?:Zone|Stage)\s+(\d+)", text)
            out.append({"page": pno + 1, "kind": "mview",
                        "label": f"Stage {m.group(1)}" if m else f"Page {pno + 1}"})
    doc.close()
    return out


def extract_interval(path, pageno, sample_sec=1.0):
    """One chart page -> the same stage payload shape as /api/extract."""
    import numpy as np
    doc = fitz.open(path)
    page = doc[pageno - 1]
    if "(IFS v" in page.get_text():
        meta, samples, data, chinfo = ifs.extract_page(page, sample_sec)
        style = {"Tr Press": "#1d5bd8", "Slurry Rate": "#c8372d",
                 "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a3b9b"}
        extra = ["#c07f16", "#118a8a", "#94261f"]
        channels = []
        for i, (col, vals) in enumerate(data.items()):
            channels.append({
                "key": col, "label": chinfo[col]["label"], "unit": chinfo[col]["unit"],
                "color": style.get(col, extra[i % len(extra)]),
                "values": [None if np.isnan(v) else round(float(v), 4) for v in vals],
                "gaps": [], "overlaps": [], "caveats": [],
            })
        payload = {
            "kind": "vector",
            "meta": {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                     "date": meta.date, "duration_min": meta.duration_min,
                     "warnings": meta.warnings},
            "n": int(len(samples)), "sample_sec": float(sample_sec),
            "channels": channels,
        }
    else:
        from extract import _stage_payload
        meta, samples, data = fc.extract_page(page, sample_sec=sample_sec)
        payload = _stage_payload("vector", meta, samples, data, sample_sec)
    doc.close()
    return payload
