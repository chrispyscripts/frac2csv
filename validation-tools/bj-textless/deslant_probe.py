"""Map de-slanted OCR boxes back to page coordinates, and prove it by the
spacing of the labels it recovers: these ticks are 15 minutes apart by
construction, so a correct mapping puts them at even x and a wrong one does
not."""
import sys, re, math
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, numpy as np
from PIL import Image
import auto_raster as ar

TIME_RE = re.compile(r"([A-Z][a-z]{2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")


def slanted_lines(page, clip, deg, dpi=220):
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[..., :3]
    elif pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    h, w = img.shape[0], img.shape[1]
    base = Image.fromarray(img)
    rot = base.rotate(-deg, expand=True, fillcolor=(255, 255, 255),
                      resample=Image.BICUBIC)
    W, H = rot.size
    boxes = ar.ocr_boxes(np.array(rot).astype(int), psm=6, whitelist="")
    # inverse of PIL's rotate(-deg, expand=True): un-centre, rotate by -deg
    # in screen coords, re-centre on the ORIGINAL image
    th = math.radians(-deg)
    cos, sin = math.cos(th), math.sin(th)
    lines = {}
    for b in boxes:
        lines.setdefault(b["line"], []).append(b)
    out = []
    scale = 72.0 / dpi
    for ws in lines.values():
        ws.sort(key=lambda b: b["x0"])
        text = " ".join(b["text"] for b in ws)
        xs = [(b["x0"], b["y0"], b["x1"], b["y1"]) for b in ws]
        x0 = min(v[0] for v in xs); y0 = min(v[1] for v in xs)
        x1 = max(v[2] for v in xs); y1 = max(v[3] for v in xs)
        pts = []
        for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            u, v = px - W / 2.0, py - H / 2.0
            iu = u * cos + v * sin
            iv = -u * sin + v * cos
            pts.append((iu + w / 2.0, iv + h / 2.0))
        rx0 = min(p[0] for p in pts) * scale + clip.x0
        rx1 = max(p[0] for p in pts) * scale + clip.x0
        ry0 = min(p[1] for p in pts) * scale + clip.y0
        ry1 = max(p[1] for p in pts) * scale + clip.y0
        out.append((fitz.Rect(rx0, ry0, rx1, ry1), text))
    return out


doc = fitz.open("/Volumes/For-Chris-CnC-1TB/BCER-Frac/00956-202D037H093P0900_32287/00956-202D037H093P0900_32287_COMP_2025JUL01.PDF")
pg = doc[192]
r = pg.rect
clip = fitz.Rect(0, r.height * 0.69, r.width, r.height * 0.81)
for deg in (25, 30, 35):
    got = []
    for rect, text in slanted_lines(pg, clip, deg):
        m = TIME_RE.search(text)
        if m:
            mon, day, hh, mm = m.groups()
            secs = int(hh) * 3600 + int(mm) * 60
            got.append((secs, rect.x1, rect.y1, text[:20]))
    got.sort()
    print(f"deg={deg}: {len(got)} time labels", flush=True)
    if len(got) >= 3:
        xs = [g[1] for g in got]
        d = [round(xs[i+1] - xs[i], 2) for i in range(len(xs) - 1)]
        print(f"    times : {[g[3] for g in got]}", flush=True)
        print(f"    x1    : {[round(x,1) for x in xs]}", flush=True)
        print(f"    deltas: {d}   spread={round(max(d)-min(d),2)}", flush=True)
