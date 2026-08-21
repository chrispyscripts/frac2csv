"""Every page of a Liberty filing, and what the reader made of it.

Per page: did detect fire, did extract_page succeed, what stage/date/clock
came back, every channel's range, and whether that range sits inside the
axis the SHEET prints. Failures keep their message.

Pages where detect did NOT fire are recorded with a saturated-vector count so
a missed chart can be told from a table — as a CANDIDATE only. A high count
was wrong once before (a wellbore schematic scored 4,700), so nothing here
calls an unfired page a missed chart; it says "ink-heavy, look at it".
"""
import os, sys, json, math, traceback
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz
import lib1

def _sat(page):
    """Saturated (strongly coloured) vector items — the chart-ink proxy."""
    n = 0
    try:
        for d in page.get_drawings():
            c = d.get("color") or d.get("fill")
            if not c: continue
            hi, lo = max(c), min(c)
            if hi - lo > 0.30:            # hue-bearing, not grey furniture
                n += len(d.get("items") or ())
    except Exception:
        pass
    return n

def _rng(vals):
    f = [v for v in vals if v is not None and isinstance(v, (int, float))
         and not (isinstance(v, float) and math.isnan(v))]
    if not f: return None
    return [min(f), max(f), len(f), len(vals) - len(f)]

def run(path):
    out = {"file": os.path.basename(path), "path": path, "pages": []}
    doc = fitz.open(path)
    out["npages"] = doc.page_count
    for pno in range(doc.page_count):
        page = doc[pno]
        rec = {"p": pno + 1}
        try:
            det = lib1.detect(page)
        except Exception as e:
            rec["detect_error"] = f"{type(e).__name__}: {e}"
            det = False
        rec["detect"] = bool(det)
        if not det:
            s = _sat(page)
            if s >= 400: rec["sat"] = s      # only the ink-heavy ones are news
            out["pages"].append(rec)
            continue
        try:
            meta, samples, data, units = lib1.extract_page(page)
            rec["stage"] = getattr(meta, "stage", None)
            rec["date"] = getattr(meta, "date", None)
            rec["time"] = getattr(meta, "start_time", None)
            rec["n"] = len(samples) if samples is not None else 0
            axes = getattr(meta, "axes", None) or {}
            ch = {}
            for name, vals in (data or {}).items():
                r = _rng(vals)
                ax = axes.get(name)
                ch[name] = {"range": r, "unit": (units or {}).get(name),
                            "axis": list(ax) if ax else None,
                            # a value outside the axis the sheet prints is the
                            # defect that mattered on this template
                            "outside": bool(r and ax and
                                (r[0] < ax[0] - 1e-6 or r[1] > ax[1] + 1e-6)),
                            # and one sitting exactly ON a bound is the
                            # signature of clipping into a mis-fitted range
                            "on_bound": bool(r and ax and
                                (abs(r[1] - ax[1]) < 1e-9 or
                                 abs(r[0] - ax[0]) < 1e-9 and ax[0] != 0))}
            rec["channels"] = ch
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        out["pages"].append(rec)
    doc.close()
    return out

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    try:
        r = run(src)
    except Exception:
        r = {"file": os.path.basename(src), "path": src,
             "fatal": traceback.format_exc()[-800:]}
    json.dump(r, open(dst, "w"))
    ch = sum(1 for p in r.get("pages", []) if p.get("detect"))
    ok = sum(1 for p in r.get("pages", []) if p.get("channels"))
    print(f"{os.path.basename(src)}: {r.get('npages','?')}pp "
          f"detect={ch} extracted={ok}", flush=True)
