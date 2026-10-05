"""Copy the Lab's Stacked and FracView pages into Stratum, patched.

    python3 web/scripts/sync_lab_views.py [--ref origin/main]

Stratum's well page embeds the Lab's own lab/public/stacked.html and
lab/public/fracview.html (web/public/lab/), so they keep behaving exactly as
they do beside the Lab. Three things change for that, all
applied here rather than by hand so a refresh from the Lab is one command:

  1. FracView talks only to window.opener. Embedded, there is none: every
     send goes through host(), which falls back to the parent frame.
     (Stacked already does this.)
  2. Stratum's dark theme. The Lab is light, and each page paints its canvas
     from colours written into the code, not from its CSS variables -- so the
     variables are overridden in CSS and the canvas colours are replaced in
     the script. Curves take the stage chart's colours, the selected stage
     Stratum's teal, and FracView's warnings (clock jumps, cuts) a lighter red
     that reads on dark.
  3. Its name. In FracView (Stratum's name since 2026-10-05) the Lab's
     FracView view is called Sequential, so the page says so.

Every replacement asserts how many times it matched. If the Lab rewrites one
of these lines the sync stops and names it, instead of shipping a page that
is half light and half dark.
"""
import argparse
import os
import subprocess

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_WEB)

THEME_CSS = """
  /* STRATUM THEME (web/scripts/sync_lab_views.py): Stratum's dark palette over
     the Lab's light one, so this view matches the stage chart beside it. */
  :root { --bg:#0b1620; --panel:#0b1620; --panel2:#132330; --ink:#e7f4fa; --mut:#93adb9;
          --line:#29404c; --carmine:#5ee2d0; --carmine-dk:#3fbfae; --ok:#3fb950; --warn:#e3b341; }
  .btn, select, .chankey button, .zoomctl button { background:#152936; border-color:#345260; }
  .btn.on { background:#246358; border-color:#64e8ce; color:#f2fffc; }
  .chankey button.off { background:#0f1e29; }
</style>"""

HOST = """// ---------- talking to the Lab ----------
// STRATUM PATCH: embedded in an iframe there is no opener, so talk to the
// parent frame instead. The Lab's own pop-up still finds its opener first.
function host() {
  try { if (window.opener && !window.opener.closed) return window.opener; } catch (e) { /* gone */ }
  return window.parent !== window ? window.parent : null;
}
"""

# (old, new, expected count), applied in order to the text as it stands
FRACVIEW = [
    ("// ---------- talking to the Lab ----------\n", HOST, 1),
    ("if (!window.opener || window.opener.closed || !well) return;", "if (!host() || !well) return;", 2),
    ("window.opener.postMessage(", "host().postMessage(", 3),
    ("if (window.opener && !window.opener.closed) {", "if (host()) {", 1),
    ("</style>", THEME_CSS, 1),
    # curves: the stage chart's colours
    ('const CH_COLORS = { "Tr Press": "#a31631", "Slurry Rate": "#1f6feb",\n'
     '                    "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a4fd6" };\n'
     'const FALLBACK = ["#a31631", "#1f6feb", "#1e7a34", "#7a4fd6", "#b45309"];',
     'const CH_COLORS = { "Tr Press": "#f0555a", "Slurry Rate": "#4f8ff7",\n'
     '                    "WH Prop Conc": "#3fb950", "BH Prop Conc": "#b87fd9", "BH Press": "#39c5cf" };\n'
     'const FALLBACK = ["#f0555a", "#4f8ff7", "#3fb950", "#b87fd9", "#e3b341", "#39c5cf"];', 1),
    # stage bands
    ('if (scheme === "mono") return i % 2 ? "#f3f4f6" : "#fafafa";',
     'if (scheme === "mono") return i % 2 ? "#102029" : "#0b1620";', 1),
    ('if (scheme === "contrast") return i % 2 ? "#e8edf5" : "#fdf4e3";',
     'if (scheme === "contrast") return i % 2 ? "#13263d" : "#2a2113";', 1),
    ('return i % 2 ? "#f6f7f9" : "#ffffff";', 'return i % 2 ? "#0f1e29" : "#0b1620";', 1),
    ('return "#c9ced6";', 'return "#345260";', 1),
    # the selected stage, day changes, boundaries and the sequence view
    ('i === selIdx ? "#a31631" : "#14181d"', 'i === selIdx ? "#5ee2d0" : "#e7f4fa"', 1),
    ('isNewDay ? "#a31631" : "#9aa1aa"', 'isNewDay ? "#e7f4fa" : "#7f97a4"', 1),
    ('near ? "#a31631" : (isEnd ? "#9aa1aa" : bandEdge(i))', 'near ? "#5ee2d0" : (isEnd ? "#7f97a4" : bandEdge(i))', 1),
    ('near ? "#a31631" : bandEdge(i)', 'near ? "#5ee2d0" : bandEdge(i)', 1),
    ('goesBack ? "#a31631" : "#1f6feb"', 'goesBack ? "#ff7a8a" : "#4f8ff7"', 1),
    ('back ? "#a31631" : "#1e7a34"', 'back ? "#ff7a8a" : "#3fb950"', 1),
    # what is left is one role per colour: warnings, ink, muted ink, rules
    ('"#a31631"', '"#ff7a8a"', 3),
    ('"#9aa1aa"', '"#7f97a4"', 2),
    ('"#14181d"', '"#e7f4fa"', 3),
    ('"#697077"', '"#93adb9"', 4),
    ('"#1f6feb"', '"#4f8ff7"', 1),
    ('"#e3e5e8"', '"#1b2f3b"', 1),
    ('"#eceef1"', '"#1b2f3b"', 2),
    ('"#fff"', '"#0b1620"', 1),
    ('"rgba(163,22,49,0.07)"', '"rgba(255,122,138,0.08)"', 1),
    ('"rgba(163,22,49,0.13)"', '"rgba(255,122,138,0.14)"', 1),
    ('"rgba(163,22,49,0.16)"', '"rgba(255,122,138,0.16)"', 1),
    ('"rgba(163,22,49,0.5)"', '"rgba(255,122,138,0.5)"', 1),
    ('"rgba(163,22,49,0.55)"', '"rgba(255,122,138,0.55)"', 1),
    ('"rgba(105,112,119,0.05)"', '"rgba(147,173,185,0.05)"', 1),
    ('"rgba(105,112,119,0.16)"', '"rgba(147,173,185,0.18)"', 1),
    ('"rgba(105,112,119,0.22)"', '"rgba(147,173,185,0.2)"', 1),
    ('"rgba(105,112,119,0.7)"', '"rgba(147,173,185,0.6)"', 1),
    ('"rgba(255,255,255,0.82)"', '"rgba(11,22,32,0.85)"', 1),
    ('"rgba(255,255,255,0.94)"', '"rgba(16,39,51,0.95)"', 1),
    ('"rgba(20,24,29,0.10)"', '"#5ccbb7"', 1),
    ('"rgba(20,24,29,0.35)"', '"rgba(231,244,250,0.35)"', 1),
    # in FracView (the product) this view is called Sequential
    ("<title>FracView — Carmine's Lab</title>", "<title>Sequential — Carmine's Lab</title>", 1),
    ('<div class="wordmark">FracView</div>', '<div class="wordmark">Sequential</div>', 1),
    ("Pick a well in the Lab — FracView follows whatever is selected there.",
     "Pick a well — Sequential follows the well and stage open beside it.", 2),
]

STACKED = [
    ("</style>", THEME_CSS, 1),
    ('const C = { grid: "#e3e5e8", axisText: "#697077", crosshair: "#b6bcc4",\n'
     '            ink: "#14181d", mut: "#697077" };',
     'const C = { grid: "#1b2f3b", axisText: "#93adb9", crosshair: "#9fb7c4",\n'
     '            ink: "#e7f4fa", mut: "#93adb9" };', 1),
    ('"rgba(105,112,119,0.13)"', '"rgba(147,173,185,0.12)"', 1),
    ('"rgba(163,22,49,0.13)"', '"rgba(255,122,138,0.12)"', 1),
    ('"#a31631"', '"#ff7a8a"', 1),
]


def patch(text, edits, name):
    for old, new, want in edits:
        got = text.count(old)
        if got != want:
            raise SystemExit(f"{name}: expected {want} of {old[:70]!r}, found {got} -- the Lab changed this line")
        text = text.replace(old, new)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="origin/main", help="git ref to copy the Lab's pages from")
    a = ap.parse_args()
    sha = subprocess.run(["git", "rev-parse", "--short", a.ref], cwd=_REPO, capture_output=True,
                         text=True, check=True).stdout.strip()
    os.makedirs(os.path.join(_WEB, "public", "lab"), exist_ok=True)
    for name, edits in (("stacked", STACKED), ("fracview", FRACVIEW)):
        src = subprocess.run(["git", "show", f"{a.ref}:lab/public/{name}.html"], cwd=_REPO,
                             capture_output=True, text=True, check=True).stdout
        out = patch(src, edits, name)
        head = (f"<!-- GENERATED by web/scripts/sync_lab_views.py from the Lab's lab/public/{name}.html "
                f"at {a.ref} ({sha}). Do not edit: change the Lab, or the patches in that script, and re-run. -->\n")
        assert out.startswith("<!doctype html>\n")
        out = out.replace("<!doctype html>\n", "<!doctype html>\n" + head, 1)
        path = os.path.join(_WEB, "public", "lab", f"{name}.html")
        open(path, "w").write(out)
        print(f"{name}: {len(edits)} patches -> {os.path.relpath(path, _REPO)}")


if __name__ == "__main__":
    main()
