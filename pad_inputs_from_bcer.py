"""Turn a BCER data drop into the three inputs pad_json.py wants.

    python3 pad_inputs_from_bcer.py --drop ~/Downloads/For_Chris-testing \
        --pad-set gundywest --out ../exports/bc-gundy-creek-west

A drop holds the province-wide BCER tables plus a well list for the pad:

  WellSummaryGrid-*.csv     the pad's wells: WELLID, WELLNAME, LICENSE (the WA
                            number), TD, TVD, decimal LAT/LNG, KB, UTM
  dir_survey_csv/*.csv      DIR_SURVEY for ALL of BC (~2M stations); the wells
                            we want are pulled out by WA number
  FRAC2csv-seconds/         the Lab's per-second export, one file per well --
                            only its NAME is used here, to fill FILE
  hydraulic_fracture_csv/   COMPL_WO for all of BC: one row per frac stage the
                            operator filed, with its interval -- optional

and writes cluster.tsv / trajectories.csv / surface.csv (and stage-depths.csv
when the frac table is there) beside each other.

Two things worth knowing:

  * Wells are grouped into pads by surface proximity (PAD_GAP_M), not by any
    field in the data -- BCER files a surface point per well, not a pad.
  * pad_json.py reads surface latitude/longitude as BCER's raw 'DDMMSSss'
    integers, so the decimal degrees here are encoded back into that form.
    Hundredths of an arc-second is ~0.3 m, well under the ~6 m between slots,
    and it keeps surface.csv the same shape the existing clusters use.
"""
import argparse
import csv
import glob
import math
import os
import re

PAD_GAP_M = 150.0


def to_dms_raw(deg):
    """Decimal degrees -> BCER's 'DDMMSSss' (hundredths of an arc-second)."""
    deg = abs(float(deg))
    d = int(deg)
    rest = (deg - d) * 60.0
    m = int(rest)
    s = round((rest - m) * 60.0 * 100)          # hundredths
    if s >= 6000:
        s -= 6000; m += 1
    if m >= 60:
        m -= 60; d += 1
    return f"{d}{m:02d}{s:04d}"


def metres(a, b):
    (la1, lo1), (la2, lo2) = a, b
    return math.hypot((la2 - la1) * 111320.0,
                      (lo2 - lo1) * 111320.0 * math.cos(math.radians(la1)))


def pads_by_proximity(wells):
    """Single-link clustering of surface points -> 1-based pad number per WA."""
    pads = []
    for w in sorted(wells, key=lambda w: (w["lat"], w["lon"])):
        for p in pads:
            if any(metres((w["lat"], w["lon"]), (o["lat"], o["lon"])) <= PAD_GAP_M for o in p):
                p.append(w); break
        else:
            pads.append([w])
    pads.sort(key=lambda p: -len(p))
    return {w["wa"]: i + 1 for i, p in enumerate(pads) for w in p}


def read_summary(path):
    out = []
    for r in csv.DictReader(open(path, newline="", encoding="utf-8-sig", errors="replace")):
        lic = str(r.get("LICENSE") or "").strip()
        if not lic.strip("0"):
            continue
        out.append({
            "wa": str(int(lic)),
            "uwi": (r.get("WELLID") or "").strip(),
            "name": re.sub(r"\s+", " ", (r.get("WELLNAME") or "").strip()),
            "surface_uwi": (r.get("SURFACE_UWI") or "").strip(),
            "td": (r.get("TD") or "").strip(),
            "tvd": (r.get("TVD") or "").strip(),
            "lat": float(r["LAT"]), "lon": float(r["LNG"]),
            "kb": (r.get("KB") or "").strip(),
            "utm_zone": (r.get("UTMZONE") or "").strip(),
            "utm_e": (r.get("UTMX") or "").strip(),
            "utm_n": (r.get("UTMY") or "").strip(),
        })
    return out


def read_dir_survey(path, keep):
    """DIR_SURVEY rows for the wanted WA numbers, in file order."""
    rows = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.reader(f)
        head = next(rd)
        if len(head) < 5:                      # a one-cell banner line
            head = next(rd)
        ix = {h.strip(): i for i, h in enumerate(head)}
        col = lambda *names: next((ix[n] for n in names if n in ix), None)
        c = {"wa": col("WA NUM", "WA_NUM", "WA"), "ev": col("Drilling Event", "DRILLING_EVENT"),
             "md": col("Measured Depth (m)", "MD_M"), "inc": col("Inclination (deg)", "INC_DEG"),
             "az": col("Azimuth (deg)", "AZ_DEG"), "tvd": col("TV Depth (m)", "TVD_M"),
             "ns": col("North South (m)", "NS_M"), "ew": col("East West (m)", "EW_M")}
        if c["wa"] is None:
            raise SystemExit(f"{path}: no WA column in {head}")
        for row in rd:
            if not row or c["wa"] >= len(row):
                continue
            wa = row[c["wa"]].strip().lstrip("0")
            if wa in keep:
                g = lambda k: (row[c[k]].strip() if c[k] is not None and c[k] < len(row) else "")
                rows.setdefault(wa, []).append(
                    {"ev": g("ev"), "md": g("md"), "inc": g("inc"), "az": g("az"),
                     "tvd": g("tvd"), "ns": g("ns"), "ew": g("ew")})
    return rows


MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def bcer_date(raw):
    """'20-JAN-24' -> '20240120' (what stages_from_bcer.py reads)."""
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", str(raw or "").strip())
    if not m:
        return ""
    d, mon, y = int(m.group(1)), MONTHS.get(m.group(2).upper()), int(m.group(3))
    if not mon:
        return ""
    y = y + 2000 if y < 100 else y
    return f"{y:04d}{mon:02d}{d:02d}"


def read_frac_stages(path, keep):
    """The filed frac stages for the wanted WA numbers, latest completion only."""
    rows = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.reader(f)
        head = next(rd)
        if len(head) < 5:
            head = next(rd)
        ix = {h.strip(): i for i, h in enumerate(head)}
        need = ["WA NUM", "COMPLTN DATE", "COMPLTN TOP DEPTH (m)", "COMPLTN BASE DEPTH (m)",
                "COMPLTN TYPE", "COMPLETION WORKOVER KEY", "DRILLNG EVENT", "COMPLTN EVENT"]
        if "WA NUM" not in ix:
            raise SystemExit(f"{path}: no 'WA NUM' column")
        g = lambda row, k: (row[ix[k]].strip() if k in ix and ix[k] < len(row) else "")
        for row in rd:
            if not row:
                continue
            wa = g(row, "WA NUM").lstrip("0")
            if wa in keep:
                rows.setdefault(wa, []).append(row)
    out = {}
    for wa, rs in rows.items():
        # a re-completion files its own set of stages; the newest is the well today
        latest = max((g(r, "DRILLNG EVENT"), g(r, "COMPLTN EVENT")) for r in rs)
        rs = [r for r in rs if (g(r, "DRILLNG EVENT"), g(r, "COMPLTN EVENT")) == latest]
        # deepest interval is stage 1, the way the treatment reports number them
        rs.sort(key=lambda r: -float(g(r, "COMPLTN TOP DEPTH (m)") or 0))
        out[wa] = [{"stage": i + 1, "date": bcer_date(g(r, "COMPLTN DATE")),
                    "top": g(r, "COMPLTN TOP DEPTH (m)"), "base": g(r, "COMPLTN BASE DEPTH (m)"),
                    "type": g(r, "COMPLTN TYPE"), "key": g(r, "COMPLETION WORKOVER KEY")}
                   for i, r in enumerate(rs)]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drop", required=True, help="the folder the BCER files were delivered in")
    ap.add_argument("--out", required=True, help="where to write the three inputs")
    ap.add_argument("--pad-set", required=True)
    a = ap.parse_args()

    summary = next(iter(glob.glob(os.path.join(a.drop, "WellSummaryGrid*.csv"))), None)
    if not summary:
        raise SystemExit("no WellSummaryGrid*.csv in the drop")
    surveys = next(iter(glob.glob(os.path.join(a.drop, "dir_survey_csv", "*.csv"))), None)
    surveys = next((p for p in glob.glob(os.path.join(a.drop, "dir_survey_csv", "*.csv"))
                    if "readme" not in os.path.basename(p).lower()), surveys)
    if not surveys:
        raise SystemExit("no dir_survey CSV in the drop")

    wells = read_summary(summary)
    by_wa = {w["wa"]: w for w in wells}
    pad_of = pads_by_proximity(wells)

    # the Lab's export names the completion report each well's stages come from
    files = {}
    for p in glob.glob(os.path.join(a.drop, "FRAC2csv-seconds", "*-seconds.csv")):
        base = os.path.basename(p)[: -len("-seconds.csv")]
        m = re.search(r"_(\d{4,6})_", base)
        if m:
            files[m.group(1).lstrip("0")] = base + ".pdf"

    print(f"{len(wells)} wells, {len(set(pad_of.values()))} pad(s) by surface proximity")
    stations = read_dir_survey(surveys, set(by_wa))
    missing = [wa for wa in by_wa if wa not in stations]
    if missing:
        print("  no DIR_SURVEY stations for WA:", ", ".join(sorted(missing)))

    os.makedirs(a.out, exist_ok=True)
    cl = os.path.join(a.out, "cluster.tsv")
    with open(cl, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["PAD", "WA", "WELL", "UWI", "TD_M", "PAD_LAT", "PAD_LON", "FILE"])
        for pad in sorted(set(pad_of.values())):
            members = [x for x in wells if pad_of[x["wa"]] == pad]
            plat = sum(x["lat"] for x in members) / len(members)
            plon = sum(x["lon"] for x in members) / len(members)
            for x in sorted(members, key=lambda x: x["name"]):
                w.writerow([pad, x["wa"], x["name"], x["uwi"], x["td"],
                            f"{plat:.6f}", f"{plon:.6f}", files.get(x["wa"], "")])

    tr = os.path.join(a.out, "trajectories.csv")
    n = 0
    with open(tr, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PAD", "WA", "WELL", "UWI", "DRILLING_EVENT", "MD_M", "INC_DEG", "AZ_DEG", "TVD_M", "NS_M", "EW_M"])
        for wa, rows in sorted(stations.items()):
            x = by_wa[wa]
            for s in rows:
                w.writerow([pad_of[wa], wa, x["name"], x["uwi"], s["ev"], s["md"],
                            s["inc"], s["az"], s["tvd"], s["ns"], s["ew"]])
                n += 1

    sf = os.path.join(a.out, "surface.csv")
    with open(sf, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["WA", "lat_raw", "lon_raw", "elev", "loc", "utm_zone", "utm_n", "utm_e"])
        for x in sorted(wells, key=lambda x: x["wa"]):
            w.writerow([x["wa"], to_dms_raw(x["lat"]), to_dms_raw(x["lon"]), x["kb"],
                        x["surface_uwi"], x["utm_zone"], x["utm_n"], x["utm_e"]])

    frac = next((p for p in glob.glob(os.path.join(a.drop, "hydraulic_fracture_csv", "*.csv"))
                 if "hydraulic_fracture" in os.path.basename(p).lower()), None)
    dp = ""
    if frac:
        stages = read_frac_stages(frac, set(by_wa))
        dp = os.path.join(a.out, "stage-depths.csv")
        total = 0
        with open(dp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["PAD", "WA", "WELL", "STAGE_BY_DEPTH", "DATE", "TOP_MD_M", "BASE_MD_M",
                        "COMPLETION_TYPE", "STIM_TYPE", "STIM_VOL_M3", "STIM_PRESS_KPA", "SUMMARY", "WORKOVER_KEY"])
            for wa, rs in sorted(stages.items()):
                for s_ in rs:
                    w.writerow([pad_of[wa], wa, by_wa[wa]["name"], s_["stage"], s_["date"],
                                s_["top"], s_["base"], s_["type"], "", "", "", "", s_["key"]])
                    total += 1
        print(f"  {dp}  ({total} filed stages across {len(stages)} wells)")

    print(f"  {cl}\n  {tr}  ({n} stations)\n  {sf}")
    print(f"next: python3 pad_json.py --cluster {cl} --surveys {tr} --surface {sf} --pad-set {a.pad_set}")


if __name__ == "__main__":
    main()
