#!/usr/bin/env python3
"""Frac2CSV — desktop app: frac chart PDF -> 1-second CSV time series.

Drop in MView-style frac stage PDFs, get one CSV per stage page, with a
preview chart so you can eyeball the extraction before trusting it.
"""
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import fitz
import numpy as np

import auto_raster as ar
import frac_core as fc
import raster_core as rc
import report as rp

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


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


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("980x680")
        root.configure(bg=BG)
        self.files = []

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Button(top, text="Add PDFs…", command=self.add_files,
                  bg=PANEL, fg=FG, activebackground=ACC, relief="flat",
                  padx=14, pady=4).pack(side="left")
        tk.Button(top, text="Extract All", command=self.extract_all,
                  bg="#238636", fg="white", activebackground="#2ea043",
                  relief="flat", padx=14, pady=4).pack(side="left", padx=8)
        tk.Label(top, text="Sample interval (s):", bg=BG, fg=MUT).pack(side="left", padx=(16, 4))
        self.interval = tk.StringVar(value="1.0")
        tk.Entry(top, textvariable=self.interval, width=6, bg=PANEL, fg=FG,
                 insertbackground=FG, relief="flat").pack(side="left")
        self.report_on = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Interactive HTML report", variable=self.report_on,
                       bg=BG, fg=MUT, selectcolor=PANEL, activebackground=BG,
                       activeforeground=FG).pack(side="left", padx=(14, 0))
        tk.Label(top, text="Outputs are saved next to each input file.", bg=BG, fg=MUT).pack(side="right")

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
        for label, key, default, width in [
                ("Duration min", "duration", "80", 5), ("Press max", "pmax", "90", 5),
                ("Rate max", "ratemax", "18", 5), ("Conc max", "concmax", "900", 6),
                ("UWI", "uwi", "", 18), ("Stage", "stage", "", 4),
                ("Date", "date", "", 10)]:
            tk.Label(fb, text=label + ":", bg=BG, fg=MUT).pack(side="left", padx=(10, 2))
            var = tk.StringVar(value=default)
            self.fb_vars[key] = var
            tk.Entry(fb, textvariable=var, width=width, bg=PANEL, fg=FG,
                     insertbackground=FG, relief="flat").pack(side="left")

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
        self.say("Add one or more frac chart PDFs, then hit Extract All. "
                 "UWI, stage, date, duration and axis scales are read from each page automatically.")

    def say(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose frac chart PDFs or images",
            filetypes=[("Frac charts", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("PDF files", "*.pdf"), ("Images", "*.png *.jpg *.jpeg")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.filelist.insert("end", os.path.basename(p))

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
        for path in files:
            name = os.path.basename(path)
            base = os.path.splitext(path)[0]
            ext = os.path.splitext(path)[1].lower()

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
            for pno in range(len(doc)):
                label = f"{name} p{pno + 1}"
                try:
                    page = doc[pno]
                    if fc.page_kind(page) == "vector":
                        meta, samples, data = fc.extract_page(page, sample_sec=interval)
                        suffix = f"-stage-{meta.stage}" if meta.stage else f"-p{pno + 1}"
                        out = f"{base}{suffix}.csv"
                        n, cols = fc.write_csv(out, meta, samples, data, interval)
                        if self.report_on.get():
                            rep = rp.write_report(out[:-4] + ".html", meta, samples,
                                                  data, interval, kind="vector")
                            self.ui(lambda r=rep: self.say(
                                f"   report → {os.path.basename(r)} (open in a browser)"))
                        msg = (f"OK {label}: detected input type = VECTOR chart (lossless "
                               f"geometry) | {meta.title or 'untitled'} | UWI {meta.uwi or '?'} "
                               f"stage {meta.stage or '?'} | {meta.duration_min:g} min → "
                               f"{n} rows x {len(cols)} channels → {os.path.basename(out)}")
                        if meta.warnings:
                            msg += "  [warnings: " + "; ".join(meta.warnings) + "]"
                        self.ui(lambda m=msg: self.say(m))
                        self.ui(lambda s=samples, d=data, mt=meta: self.draw(s, d, mt))
                    else:
                        meta = self._fallback_meta()
                        meta = fc.detect_text_meta(page, meta)  # text layer may survive flattening
                        self.ui(lambda l=label: self.say(
                            f"{l}: detected input type = raster/flattened PDF page "
                            f"(no vector curves — pixel tracing)"))
                        img = rc.pixmap_to_array(page.get_pixmap(dpi=300))
                        pbase = base if len(doc) == 1 else f"{base}-p{pno + 1}"
                        self._extract_raster(img, meta, interval, pbase, label)
                except Exception as e:
                    self.ui(lambda e=e, l=label: self.say(f"SKIP {l}: {e}"))
                    continue
            doc.close()
        self.ui(lambda: self.say("Done."))

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
