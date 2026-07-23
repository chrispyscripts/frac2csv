#!/usr/bin/env python3
"""Frac2CSV — desktop app: frac chart PDF -> 1-second CSV time series.

Drop in MView-style frac stage PDFs, get one CSV per stage page, with a
preview chart so you can eyeball the extraction before trusting it.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import fitz
import numpy as np

import aliases
import auto_raster as ar
import frac_core as fc
import pipeline
import pipeline_export as pe
import raster_core as rc
import report as rp

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def _meta_obj(md):
    """dict from pipeline -> fc.PageMeta for CSV/report writing."""
    m = fc.PageMeta(uwi=md.get("uwi", ""), stage=str(md.get("stage") or ""),
                    date=md.get("date", ""),
                    start_time=md.get("start_time") or "00:00:00",
                    title=md.get("title", ""))
    m.duration_min = md.get("duration_min", 0.0) or 0.0
    m.warnings = list(md.get("warnings", []))
    return m


def _canon_data(data):
    """Rename vendor curve names to Carmine's canonical columns (alias
    table); unmapped names survive as-is. Preserves insertion order."""
    out, seen = {}, set()
    for name, vals in data.items():
        canonical = aliases.canon(name)
        key = canonical if canonical and canonical not in seen else name
        seen.add(key)
        out[key] = vals
    return out


def sniff_kind(path):
    """'pdf' | 'image' | None, by file content (magic bytes), not extension."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if (head.startswith(b"\x89PNG\r\n\x1a\n") or head[:2] == b"\xff\xd8"
            or head[:4] in (b"II*\x00", b"MM\x00*") or head[:2] == b"BM"):
        return "image"
    return None

APP_TITLE = "Frac2CSV  —  frac chart PDF → 1-sec CSV"
BG, PANEL, FG, MUT, ACC = "#0d1117", "#161b22", "#e6edf3", "#8b949e", "#58a6ff"
SERIES_COLORS = {"Tr Press": "#4f8ff7", "Slurry Rate": "#f0555a",
                 "WH Prop Conc": "#3fb950", "BH Prop Conc": "#b87fd9",
                 "series-red": "#f0555a", "series-green": "#3fb950",
                 "series-blue": "#4f8ff7", "series-magenta": "#b87fd9"}
FALLBACK_COLOR = "#e6b84b"


def _button(parent, text, command, primary=False):
    """macOS Aqua ignores custom button backgrounds but still applies the
    text color — white-on-white made the buttons look blank/disabled. Use
    native styling on darwin, the dark styling elsewhere."""
    if sys.platform == "darwin":
        return tk.Button(parent, text=text, command=command, padx=10, pady=2)
    if primary:
        return tk.Button(parent, text=text, command=command, bg="#238636",
                         fg="white", activebackground="#2ea043",
                         relief="flat", padx=14, pady=4)
    return tk.Button(parent, text=text, command=command, bg=PANEL, fg=FG,
                     activebackground=ACC, relief="flat", padx=14, pady=4)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1240x760")
        root.configure(bg=BG)
        self.files = []

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=14, pady=(12, 6))
        _button(top, "Add PDFs / .txt list…", self.add_files).pack(side="left")
        _button(top, "Extract All", self.extract_all,
                primary=True).pack(side="left", padx=8)
        tk.Label(top, text="Sample interval (s):", bg=BG, fg=MUT).pack(side="left", padx=(16, 4))
        self.interval = tk.StringVar(value="1.0")
        tk.Entry(top, textvariable=self.interval, width=6, bg=PANEL, fg=FG,
                 insertbackground=FG, relief="flat").pack(side="left")
        self.report_on = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Per-stage HTML reports", variable=self.report_on,
                       bg=BG, fg=MUT, selectcolor=PANEL, activebackground=BG,
                       activeforeground=FG).pack(side="left", padx=(14, 0))
        tk.Label(top, text="Exports save next to each input PDF.", bg=BG, fg=MUT).pack(side="right")

        # export format (matches the web Lab: one combined file per well)
        ex = tk.Frame(root, bg=BG)
        ex.pack(fill="x", padx=14, pady=(0, 2))
        tk.Label(ex, text="Export:", bg=BG, fg=MUT).pack(side="left")
        self.fmt = tk.StringVar(value="both")
        for label, val in (("CSV", "csv"), ("Excel", "xlsx"), ("Both", "both")):
            tk.Radiobutton(ex, text=label, value=val, variable=self.fmt,
                           bg=BG, fg=MUT, selectcolor=PANEL, activebackground=BG,
                           activeforeground=FG).pack(side="left", padx=(4, 0))
        tk.Label(ex, text="| Excel layout:", bg=BG, fg=MUT).pack(side="left", padx=(10, 0))
        self.xlsx_tabs = tk.StringVar(value="tabs")
        for label, val in (("Tab per stage", "tabs"), ("One sheet", "single")):
            tk.Radiobutton(ex, text=label, value=val, variable=self.xlsx_tabs,
                           bg=BG, fg=MUT, selectcolor=PANEL, activebackground=BG,
                           activeforeground=FG).pack(side="left", padx=(4, 0))

        # fallback settings for raster inputs with no readable metadata
        fb = tk.Frame(root, bg=BG)
        fb.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(fb, text="Raster mode:", bg=BG, fg=MUT).pack(side="left")
        self.raster_mode = tk.StringVar(value="template")
        for label, val in (("MView template", "template"), ("Auto-calibrate (OCR)", "auto")):
            tk.Radiobutton(fb, text=label, value=val, variable=self.raster_mode,
                           bg=BG, fg=MUT, selectcolor=PANEL, activebackground=BG,
                           activeforeground=FG).pack(side="left", padx=(4, 0))
        tk.Label(fb, text="| Template fallback scales:",
                 bg=BG, fg=MUT).pack(side="left", padx=(10, 0))
        self.fb_vars = {}

        def add_fields(row, fields):
            for label, key, default, width in fields:
                tk.Label(row, text=label + ":", bg=BG, fg=MUT).pack(
                    side="left", padx=(10, 2))
                var = tk.StringVar(value=default)
                self.fb_vars[key] = var
                tk.Entry(row, textvariable=var, width=width, bg=PANEL, fg=FG,
                         insertbackground=FG, relief="flat").pack(side="left")

        add_fields(fb, [("Duration min", "duration", "80", 5),
                        ("Press max", "pmax", "90", 5),
                        ("Rate max", "ratemax", "18", 5),
                        ("Conc max", "concmax", "900", 6)])
        fb2 = tk.Frame(root, bg=BG)
        fb2.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(fb2, text="Fallback metadata (raster only):",
                 bg=BG, fg=MUT).pack(side="left")
        add_fields(fb2, [("UWI", "uwi", "", 18), ("Stage", "stage", "", 4),
                         ("Date", "date", "", 10)])

        mid = tk.Frame(root, bg=BG)
        mid.pack(fill="both", expand=True, padx=14)
        left = tk.Frame(mid, bg=BG)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Files", bg=BG, fg=MUT, anchor="w").pack(fill="x")
        self.filelist = tk.Listbox(left, width=42, bg=PANEL, fg=FG, relief="flat",
                                   selectbackground=ACC, highlightthickness=0)
        self.filelist.pack(fill="y", expand=True, pady=(2, 0))

        right = tk.Frame(mid, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(right, text="Preview (last extracted page)", bg=BG, fg=MUT,
                 anchor="w").pack(fill="x")
        self.canvas = tk.Canvas(right, bg=PANEL, highlightthickness=0, height=330)
        self.canvas.pack(fill="both", expand=True, pady=(2, 0))

        tk.Label(root, text="Log", bg=BG, fg=MUT, anchor="w").pack(fill="x", padx=14, pady=(8, 0))
        self.log = tk.Text(root, height=9, bg=PANEL, fg=FG, relief="flat",
                           highlightthickness=0, state="disabled", wrap="word")
        self.log.pack(fill="x", padx=14, pady=(2, 12))
        ocr = "on" if pipeline.raster_available() else "OFF (tesseract not found)"
        self.say("Add one or more frac report PDFs, then hit Extract All. "
                 "Every supported chart system is auto-detected — MView, "
                 "Halliburton IFS, Leucrotta/Liberty, Canyon, BJ, plus text "
                 "reports (SK FracR, Peloton WellView, Trican). Scanned/raster "
                 f"plots (STEP, Halliburton treatment plots) use OCR: {ocr}. "
                 "Each well exports as ONE combined CSV/Excel file (all stages, "
                 "split by the STAGE column) saved beside the source PDF. "
                 "Drop a .txt drive list to batch a whole folder tree.")

    def say(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose frac report PDFs, images, or a .txt file list",
            filetypes=[("Frac charts + lists",
                        "*.pdf *.txt *.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("PDF files", "*.pdf"), ("File lists", "*.txt"),
                       ("Images", "*.png *.jpg *.jpeg")])
        for p in paths:
            if p.lower().endswith(".txt"):
                self.add_manifest(p)
            elif p not in self.files:
                self.files.append(p)
                self.filelist.insert("end", os.path.basename(p))

    def add_manifest(self, txt_path):
        """A drive list: 'UWI  K:\\BCER-Frac\\<folder>\\<file>.PDF' per line.
        Each row's PDF is queued; exports save into that PDF's own folder."""
        try:
            text = open(txt_path, encoding="utf-8", errors="replace").read()
        except OSError as e:
            self.say(f"ERROR reading {os.path.basename(txt_path)}: {e}")
            return
        rows = pe.parse_manifest(text)
        if not rows:
            self.say(f"{os.path.basename(txt_path)}: no 'UWI  <path>.PDF' rows found.")
            return
        txt_dir = os.path.dirname(os.path.abspath(txt_path))
        roots = [txt_dir]              # search the TXT's own folder first
        added = missing = 0
        asked = False
        indexes = {}
        for uwi, path in rows:
            real = None
            for root in roots:
                real = pe.resolve_manifest_path(path, root)
                if real is None:
                    if root not in indexes:   # lazy: filename match anywhere
                        self.say("   indexing PDFs under "
                                 + os.path.basename(root) + "…")
                        self.root.update_idletasks()
                        indexes[root] = pe.index_pdfs(root)
                    real = pe.resolve_manifest_path(path, root, indexes[root])
                if real:
                    break
            if real is None and not asked:
                # the list's drive paths don't exist here (other machine /
                # different drive letter) — ask where the files actually live
                asked = True
                self.say("   list paths don't match this machine — pick the "
                         "folder that holds these files (e.g. BCER-Frac)…")
                picked = filedialog.askdirectory(
                    title="Pick the folder that holds the listed PDFs")
                if picked:
                    roots.append(picked)
                    real = pe.resolve_manifest_path(path, picked)
                    if real is None:
                        self.say("   indexing PDFs under "
                                 + os.path.basename(picked) + "…")
                        self.root.update_idletasks()
                        indexes[picked] = pe.index_pdfs(picked)
                        real = pe.resolve_manifest_path(path, picked,
                                                        indexes[picked])
            if real is None:
                missing += 1
                self.say(f"   ✗ not found: {path}")
                continue
            if real not in self.files:
                self.files.append(real)
                self.filelist.insert("end", os.path.basename(real))
                added += 1
        self.say(f"{os.path.basename(txt_path)}: {len(rows)} listed → "
                 f"{added} queued" + (f", {missing} missing" if missing else "") +
                 ". Exports will save beside each PDF.")

    def extract_all(self):
        if not self.files:
            self.say("No files added yet.")
            return
        try:
            interval = float(self.interval.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            self.say("Bad sample interval; using 1.0 s.")
            interval = 1.0
        threading.Thread(target=self._work, args=(list(self.files), interval),
                         daemon=True).start()

    def _fallback_meta(self):
        """PageMeta built from the raster-fallback fields."""
        g = lambda k: self.fb_vars[k].get().strip()
        meta = fc.PageMeta(uwi=g("uwi"), stage=g("stage"), date=g("date"))
        try:
            meta.duration_min = float(g("duration"))
            meta.pressure_max = float(g("pmax"))
            meta.rate_max = float(g("ratemax"))
            meta.conc_max = float(g("concmax"))
        except ValueError:
            pass
        return meta

    def _extract_raster(self, img, meta, interval, base, page_note):
        """Shared raster path for image files and rasterized PDF pages."""
        if self.raster_mode.get() == "auto":
            return self._extract_raster_auto(img, meta, interval, base, page_note)
        fullscale = {"pressure": meta.pressure_max, "rate": meta.rate_max,
                     "conc": meta.conc_max}
        samples, data, quality = rc.trace(img, meta.duration_min, fullscale,
                                          sample_sec=interval)
        suffix = f"-stage-{meta.stage}" if meta.stage else ""
        out = f"{base}{suffix or '-extracted'}.csv"
        n, cols = fc.write_csv(out, meta, samples, data, interval)
        if self.report_on.get():
            rep = rp.write_report(out[:-4] + ".html", meta, samples, data,
                                  interval, kind="raster", quality=quality)
            self.ui(lambda r=rep: self.say(f"   report → {os.path.basename(r)} (open in a browser)"))
        self.ui(lambda: self.say(
            f"OK {page_note}: RASTER input — pixel tracing (reduced fidelity vs vector). "
            f"{meta.duration_min:g} min → {n} rows x {len(cols)} channels → {os.path.basename(out)}"))
        if meta.warnings:
            self.ui(lambda: self.say(
                "   [metadata: " + "; ".join(meta.warnings) +
                " — fill the raster-fallback fields to set these]"))
        self.ui(lambda: self.say(
            "   ⚠ Raster caveat: values are estimates from pixels; where curves overlap "
            "or the scan is unreadable, timeframes below are interpolated/less reliable:"))
        for name in cols:
            for cav in quality[name].caveats():
                self.ui(lambda name=name, cav=cav: self.say(f"   ⚠ {name}: {cav}"))
        self.ui(lambda s=samples, d=data, mt=meta: self.draw(s, d, mt))

    def _extract_raster_auto(self, img, meta, interval, base, page_note):
        """Auto-calibrating raster mode: unknown templates, needs tesseract."""
        if not ar.available():
            self.ui(lambda: self.say(
                f"SKIP {page_note}: auto-calibrate needs the tesseract OCR engine "
                f"(install it, or switch to MView template mode)"))
            return
        samples, channels, info = ar.extract(img, sample_sec=interval)
        data = {c["key"]: c["values"] for c in channels}
        style = {c["key"]: c for c in channels}
        meta.duration_min = info["duration_s"] / 60.0
        suffix = f"-stage-{meta.stage}" if meta.stage else ""
        out = f"{base}{suffix or '-autocal'}.csv"
        n, cols = fc.write_csv(out, meta, samples, data, interval)
        if self.report_on.get():
            rep = rp.write_report(out[:-4] + ".html", meta, samples, data,
                                  interval, kind="raster", channel_style=style)
            self.ui(lambda r=rep: self.say(f"   report → {os.path.basename(r)}"))
        chdesc = ", ".join(f"{c['key']} ({c['ticks']} axis ticks, "
                           f"{c['coverage']:.0%} coverage)" for c in channels)
        self.ui(lambda: self.say(
            f"OK {page_note}: AUTO-CALIBRATED raster — axes read by OCR. "
            f"{meta.duration_min:.0f} min → {n} rows | {chdesc} → {os.path.basename(out)}"))
        self.ui(lambda: self.say(
            "   ⚠ Auto mode: channel names come from curve colors (units unknown — "
            "read them off the chart); values are estimates from pixels."))
        for note in info["notes"]:
            self.ui(lambda m=note: self.say(f"   ⚠ {m}"))
        self.ui(lambda s=samples, d=data, mt=meta: self.draw(s, d, mt))

    def _work(self, files, interval):
        total = len(files)
        for fi, path in enumerate(files, 1):
            name = os.path.basename(path)
            base = os.path.splitext(path)[0]
            ext = os.path.splitext(path)[1].lower()
            # immediate feedback — big files take a minute before results log
            self.ui(lambda i=fi, t=total, n=name: self.say(
                f"▶ [{i}/{t}] processing {n} …"))

            try:
                kind = sniff_kind(path)
            except OSError as e:
                self.ui(lambda e=e, n=name: self.say(f"ERROR reading {n}: {e}"))
                continue
            if kind is None:
                kind = "image" if ext in IMAGE_EXTS else "pdf"
                self.ui(lambda n=name: self.say(
                    f"{n}: unrecognized file signature — guessing from extension"))
            elif (kind == "pdf") != (ext == ".pdf"):
                self.ui(lambda n=name, k=kind: self.say(
                    f"{n}: file content is {k.upper()} despite the {ext or 'missing'} "
                    f"extension — processing as {k.upper()}"))

            if kind == "image":
                try:
                    img = rc.pixmap_to_array(fitz.Pixmap(path))
                    meta = self._fallback_meta()
                    self.ui(lambda n=name: self.say(
                        f"{n}: detected input type = raster IMAGE (no embedded text/geometry; "
                        f"using raster-fallback settings for axis scales)"))
                    self._extract_raster(img, meta, interval, base, name)
                except Exception as e:
                    self.ui(lambda e=e, n=name: self.say(f"SKIP {n}: {e}"))
                continue

            try:
                doc = fitz.open(path)
            except Exception as e:
                self.ui(lambda e=e, n=name: self.say(f"ERROR opening {n}: {e}"))
                continue
            try:
                results, notes = pipeline.extract_document(
                    doc, sample_sec=interval, enable_raster=True, filename=name)
            except Exception as e:
                self.ui(lambda e=e, n=name: self.say(f"ERROR {n}: {e}"))
                doc.close()
                continue

            n_series = sum(1 for r in results if r["type"] == "series")
            n_table = sum(1 for r in results if r["type"] == "table")
            self.ui(lambda n=name, s=n_series, t=n_table, p=len(doc): self.say(
                f"{n}: {p} pages → {s} chart stage(s) + {t} engineering table(s)"))

            series = [r for r in results if r["type"] == "series"]
            idx = 0
            for r in results:
                if r["type"] == "table":
                    idx += 1
                    try:
                        self._write_table(r, base, idx)
                    except Exception as e:
                        self.ui(lambda e=e, n=name: self.say(
                            f"   SKIP one table in {n}: {e}"))
            if series:
                try:
                    self._write_well(series, base, name)
                except Exception as e:
                    self.ui(lambda e=e, n=name: self.say(f"   ERROR exporting {n}: {e}"))
            for note in notes:
                self.ui(lambda m=note: self.say(f"   · {m}"))
            doc.close()
        self.ui(lambda: self.say("Done."))

    def _write_well(self, series, base, name):
        """One combined export per well (matches the web Lab): every stage
        stacked in a single CSV/XLSX, saved beside the source PDF."""
        model = pe.build_well(series, fallback_uwi=pe.filename_uwi(name))
        n_stages = len(model["blocks"])
        written = []
        fmt = self.fmt.get()
        if fmt != "xlsx":
            with open(base + ".csv", "w", newline="") as f:
                f.write(pe.well_csv(model))
            written.append(os.path.basename(base) + ".csv")
        if fmt != "csv":
            tabs = self.xlsx_tabs.get() == "tabs"
            with open(base + ".xlsx", "wb") as f:
                f.write(pe.well_xlsx(model, tabs))
            written.append(os.path.basename(base) + ".xlsx")
        rastery = any("raster" in r["source"] for r in series)
        self.ui(lambda w=written, s=n_stages: self.say(
            f"   OK {s} stage(s) → {', '.join(w)} (saved beside the PDF)"))
        if rastery:
            self.ui(lambda: self.say(
                "   ⚠ Raster caveat: some charts were pixel-traced; values "
                "there are estimates."))
        if self.report_on.get():
            for r in series:
                meta = _meta_obj(r["meta"])
                data = _canon_data(r["data"])
                stage = r["meta"].get("stage") or "x"
                rep = rp.write_report(
                    f"{base}-stage-{stage}.html", meta, r["samples"], data,
                    1.0, kind="raster" if "raster" in r["source"] else "vector")
            self.ui(lambda n=len(series): self.say(
                f"   {n} per-stage HTML report(s) written"))
        # preview the first stage
        r0 = series[0]
        self.ui(lambda r=r0: self.draw(r["samples"], _canon_data(r["data"]),
                                       _meta_obj(r["meta"])))

    def _write_table(self, r, base, idx):
        import csv as _csv
        out = f"{base}-stages-{idx}.csv" if idx > 1 else f"{base}-stages.csv"
        with open(out, "w", newline="") as f:
            w = _csv.writer(f)
            if r.get("well") or r.get("uwi"):
                w.writerow(["well", r.get("well", ""), "uwi", r.get("uwi", ""),
                            "formation", r.get("formation", "")])
            w.writerow(r["columns"])
            for row in r["rows"]:
                w.writerow(row)
        self.ui(lambda o=out, r=r: self.say(
            f"   OK {r['source']} | {len(r['rows'])} stage rows x "
            f"{len(r['columns'])} fields → {os.path.basename(o)}"))

    def ui(self, fn):
        self.root.after(0, fn)

    def draw(self, samples, data, meta):
        cv = self.canvas
        cv.delete("all")
        W = max(cv.winfo_width(), 400)
        H = max(cv.winfo_height(), 240)
        PL, PR, PT, PB = 46, 10, 26, 22
        t_max = samples[-1] if len(samples) else 1
        cv.create_text(PL, 12, text=f"{meta.title}  —  stage {meta.stage}, "
                       f"{meta.duration_min:g} min, {len(samples)} samples",
                       fill=MUT, anchor="w", font=("TkDefaultFont", 10))
        for name, vals in data.items():
            vmax = np.nanmax(vals) if np.isfinite(np.nanmax(vals)) else 1
            vmax = vmax * 1.08 if vmax > 0 else 1
            color = SERIES_COLORS.get(name, FALLBACK_COLOR)
            pts = []
            step = max(1, len(samples) // (2 * W))
            for i in range(0, len(samples), step):
                if np.isnan(vals[i]):
                    if len(pts) > 3:
                        cv.create_line(*pts, fill=color, width=1)
                    pts = []
                    continue
                x = PL + samples[i] / t_max * (W - PL - PR)
                y = PT + (1 - vals[i] / vmax) * (H - PT - PB)
                pts += [x, y]
            if len(pts) > 3:
                cv.create_line(*pts, fill=color, width=1)
        # x labels
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            x = PL + frac * (W - PL - PR)
            cv.create_text(x, H - 10, text=f"{frac * t_max / 60:g} min", fill=MUT,
                           font=("TkDefaultFont", 9))
        # legend
        lx = PL
        for name in data:
            color = SERIES_COLORS.get(name, FALLBACK_COLOR)
            cv.create_line(lx, PT - 5, lx + 16, PT - 5, fill=color, width=3)
            cv.create_text(lx + 20, PT - 5, text=name, fill=MUT, anchor="w",
                           font=("TkDefaultFont", 9))
            lx += 20 + 8 * len(name) + 24


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
