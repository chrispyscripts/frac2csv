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

import frac_core as fc

APP_TITLE = "Frac2CSV  —  frac chart PDF → 1-sec CSV"
BG, PANEL, FG, MUT, ACC = "#0d1117", "#161b22", "#e6edf3", "#8b949e", "#58a6ff"
SERIES_COLORS = {"Tr Press": "#4f8ff7", "Slurry Rate": "#f0555a",
                 "WH Prop Conc": "#3fb950", "BH Prop Conc": "#b87fd9"}


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
        tk.Label(top, text="CSVs are saved next to each PDF.", bg=BG, fg=MUT).pack(side="right")

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
            title="Choose frac chart PDFs", filetypes=[("PDF files", "*.pdf")])
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

    def _work(self, files, interval):
        for path in files:
            try:
                doc = fitz.open(path)
            except Exception as e:
                self.ui(lambda e=e, p=path: self.say(f"ERROR opening {os.path.basename(p)}: {e}"))
                continue
            base = os.path.splitext(path)[0]
            for pno in range(len(doc)):
                label = f"{os.path.basename(path)} p{pno + 1}"
                try:
                    meta, samples, data = fc.extract_page(doc[pno], sample_sec=interval)
                    suffix = f"-stage-{meta.stage}" if meta.stage else f"-p{pno + 1}"
                    out = f"{base}{suffix}.csv"
                    n, cols = fc.write_csv(out, meta, samples, data, interval)
                except Exception as e:
                    self.ui(lambda e=e, l=label: self.say(f"SKIP {l}: {e}"))
                    continue
                msg = (f"OK {label}: {meta.title or 'untitled'} | UWI {meta.uwi or '?'} "
                       f"stage {meta.stage or '?'} | {meta.duration_min:g} min → "
                       f"{n} rows x {len(cols)} channels → {os.path.basename(out)}")
                if meta.warnings:
                    msg += "  [warnings: " + "; ".join(meta.warnings) + "]"
                self.ui(lambda m=msg: self.say(m))
                self.ui(lambda s=samples, d=data, mt=meta: self.draw(s, d, mt))
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
            pts = []
            step = max(1, len(samples) // (2 * W))
            for i in range(0, len(samples), step):
                if np.isnan(vals[i]):
                    if len(pts) > 3:
                        cv.create_line(*pts, fill=SERIES_COLORS[name], width=1)
                    pts = []
                    continue
                x = PL + samples[i] / t_max * (W - PL - PR)
                y = PT + (1 - vals[i] / vmax) * (H - PT - PB)
                pts += [x, y]
            if len(pts) > 3:
                cv.create_line(*pts, fill=SERIES_COLORS[name], width=1)
        # x labels
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            x = PL + frac * (W - PL - PR)
            cv.create_text(x, H - 10, text=f"{frac * t_max / 60:g} min", fill=MUT,
                           font=("TkDefaultFont", 9))
        # legend
        lx = PL
        for name, color in SERIES_COLORS.items():
            if name in data:
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
