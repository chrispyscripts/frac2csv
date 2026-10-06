"""Copy the Lab's Stacked and FracView pages into Stratum, patched.

    python3 web/scripts/sync_lab_views.py [--ref origin/main]

Stratum's well page embeds the Lab's own lab/public/stacked.html and
lab/public/fracview.html (web/public/lab/), so they keep behaving exactly as
they do beside the Lab. Three things change for that, all
applied here rather than by hand so a refresh from the Lab is one command:

  1. FracView talks only to window.opener. Embedded, there is none: every
     send goes through host(), which falls back to the parent frame.
     (Stacked already does this.)
  2. Stratum's theme, light or dark (../theme.js sets <html data-theme> and
     fires `stratum:theme` when it changes, here as in every FracView window).
     The Lab is light, so light is the Lab's own CSS and colours; dark
     overrides its CSS variables under [data-theme=dark]. Each page paints its
     canvas from colours written into the code, not from its CSS, so every
     canvas colour becomes a pair, TH(light, dark), picked as it is drawn --
     constants the Lab evaluates once (CH_COLORS, FALLBACK, Stacked's C) become
     getters or a function so they follow too -- and each page draws again on
     `stratum:theme`. In dark, curves take the stage chart's colours, the
     selected stage Stratum's teal, and FracView's warnings (clock jumps, cuts)
     a lighter red that reads on dark; in light everything keeps the Lab's
     colours except the selected stage, which is the light teal of the stage
     chart beside it. Stacked's curve colours come with each stage from
     wellview.js, which sends the stage again when the theme changes.

     TH's arguments are written in single quotes. The Lab writes its colours
     in double quotes, so a later pattern ("#a31631") can never match a colour
     that an earlier one has already made a pair of.
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
  /* STRATUM THEME (web/scripts/sync_lab_views.py): light is the Lab's own
     palette above; dark (../theme.js sets data-theme) is Stratum's dark palette
     over it, so this view matches the stage chart beside it. :where() keeps
     each rule at the specificity it had before it was dark-only, so the Lab's
     :hover and :active rules still win over it as they did. */
  :root[data-theme=dark] { --bg:#0b1620; --panel:#0b1620; --panel2:#132330; --ink:#e7f4fa; --mut:#93adb9;
          --line:#29404c; --carmine:#5ee2d0; --carmine-dk:#3fbfae; --ok:#3fb950; --warn:#e3b341; }
  :where([data-theme=dark]) .btn, :where([data-theme=dark]) select, :where([data-theme=dark]) .chankey button,
  :where([data-theme=dark]) .zoomctl button { background:#152936; border-color:#345260; }
  :where([data-theme=dark]) .btn.on { background:#246358; border-color:#64e8ce; color:#f2fffc; }
  :where([data-theme=dark]) .chankey button.off { background:#0f1e29; }
</style>"""

# theme.js first in <head>, as on every FracView page
THEME_JS = ('<meta name="viewport" content="width=device-width, initial-scale=1">\n',
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<script src="../theme.js"></script>\n', 1)

# the pair picker, first thing in the page script
_STRICT = '"use strict";\nconst $ = id => document.getElementById(id);\n'
PICKER = (_STRICT, _STRICT + """// STRATUM PATCH (theme): every colour drawn on the canvas is a pair, the
// Lab's own light one and Stratum's dark one, picked as it is drawn.
const TH = (light, dark) => document.documentElement.dataset.theme === "dark" ? dark : light;
""", 1)


def th(light, dark):
    """A colour for each theme, picked at draw time (single quotes: see above)."""
    return f"TH('{light}', '{dark}')"


def pair(light, dark, want):
    """Every remaining "light" literal becomes TH(light, dark)."""
    return (f'"{light}"', th(light, dark), want)


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
    THEME_JS,
    PICKER,
    # curves: the Lab's colours in light, the stage chart's in dark. Getters
    # and a function, not constants, so they are read as each frame is drawn.
    ('const CH_COLORS = { "Tr Press": "#a31631", "Slurry Rate": "#1f6feb",\n'
     '                    "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a4fd6" };\n'
     'const FALLBACK = ["#a31631", "#1f6feb", "#1e7a34", "#7a4fd6", "#b45309"];',
     f'const CH_COLORS = {{ get "Tr Press"() {{ return {th("#a31631", "#f0555a")}; }},\n'
     f'                    get "Slurry Rate"() {{ return {th("#1f6feb", "#4f8ff7")}; }},\n'
     f'                    get "WH Prop Conc"() {{ return {th("#1e7a34", "#3fb950")}; }},\n'
     f'                    get "BH Prop Conc"() {{ return {th("#7a4fd6", "#b87fd9")}; }},\n'
     f'                    get "BH Press"() {{ return {th("#0b7f8a", "#39c5cf")}; }} }};\n'
     "const FALLBACK = () => TH(['#a31631', '#1f6feb', '#1e7a34', '#7a4fd6', '#b45309'],\n"
     "                          ['#f0555a', '#4f8ff7', '#3fb950', '#b87fd9', '#e3b341', '#39c5cf']);", 1),
    ("FALLBACK[ni % FALLBACK.length]", "FALLBACK()[ni % FALLBACK().length]", 1),
    # stage bands
    ('if (scheme === "mono") return i % 2 ? "#f3f4f6" : "#fafafa";',
     f'if (scheme === "mono") return i % 2 ? {th("#f3f4f6", "#102029")} : {th("#fafafa", "#0b1620")};', 1),
    ('if (scheme === "contrast") return i % 2 ? "#e8edf5" : "#fdf4e3";',
     f'if (scheme === "contrast") return i % 2 ? {th("#e8edf5", "#13263d")} : {th("#fdf4e3", "#2a2113")};', 1),
    ('return i % 2 ? "#f6f7f9" : "#ffffff";', f'return i % 2 ? {th("#f6f7f9", "#0f1e29")} : {th("#ffffff", "#0b1620")};', 1),
    ('return "#c9ced6";', f'return {th("#c9ced6", "#345260")};', 1),
    # the selected stage: the stage chart's teal (in dark its caption only;
    # its band keeps the red it has always had there), then day changes,
    # boundaries and the sequence view
    ('i === selIdx ? "#a31631" : "#14181d"', f'i === selIdx ? {th("#0d8577", "#5ee2d0")} : {th("#14181d", "#e7f4fa")}', 1),
    ('"rgba(163,22,49,0.07)"', th("rgba(13,133,119,0.07)", "rgba(255,122,138,0.08)"), 1),
    ('"rgba(163,22,49,0.5)"', th("rgba(13,133,119,0.8)", "rgba(255,122,138,0.5)"), 1),
    ('isNewDay ? "#a31631" : "#9aa1aa"', f'isNewDay ? {th("#a31631", "#e7f4fa")} : {th("#9aa1aa", "#7f97a4")}', 1),
    ('near ? "#a31631" : (isEnd ? "#9aa1aa" : bandEdge(i))',
     f'near ? {th("#a31631", "#5ee2d0")} : (isEnd ? {th("#9aa1aa", "#7f97a4")} : bandEdge(i))', 1),
    ('near ? "#a31631" : bandEdge(i)', f'near ? {th("#a31631", "#5ee2d0")} : bandEdge(i)', 1),
    ('goesBack ? "#a31631" : "#1f6feb"', f'goesBack ? {th("#a31631", "#ff7a8a")} : {th("#1f6feb", "#4f8ff7")}', 1),
    ('back ? "#a31631" : "#1e7a34"', f'back ? {th("#a31631", "#ff7a8a")} : {th("#1e7a34", "#3fb950")}', 1),
    # what is left is one role per colour: warnings, ink, muted ink, rules
    pair("#a31631", "#ff7a8a", 3),
    pair("#9aa1aa", "#7f97a4", 2),
    pair("#14181d", "#e7f4fa", 3),
    pair("#697077", "#93adb9", 4),
    pair("#1f6feb", "#4f8ff7", 1),
    pair("#e3e5e8", "#1b2f3b", 1),
    pair("#eceef1", "#1b2f3b", 2),
    pair("#fff", "#0b1620", 1),
    pair("rgba(163,22,49,0.13)", "rgba(255,122,138,0.14)", 1),
    pair("rgba(163,22,49,0.16)", "rgba(255,122,138,0.16)", 1),
    pair("rgba(163,22,49,0.55)", "rgba(255,122,138,0.55)", 1),
    pair("rgba(105,112,119,0.05)", "rgba(147,173,185,0.05)", 1),
    pair("rgba(105,112,119,0.16)", "rgba(147,173,185,0.18)", 1),
    pair("rgba(105,112,119,0.22)", "rgba(147,173,185,0.2)", 1),
    pair("rgba(105,112,119,0.7)", "rgba(147,173,185,0.6)", 1),
    pair("rgba(255,255,255,0.82)", "rgba(11,22,32,0.85)", 1),
    pair("rgba(255,255,255,0.94)", "rgba(16,39,51,0.95)", 1),
    pair("rgba(20,24,29,0.10)", "#5ccbb7", 1),
    pair("rgba(20,24,29,0.35)", "rgba(231,244,250,0.35)", 1),
    # and draws again when the theme changes; keySig is cleared so the
    # channel key's swatches are repainted with it
    ('window.addEventListener("resize", () => draw());\n',
     'window.addEventListener("resize", () => draw());\n'
     '// STRATUM PATCH (theme): every colour is picked as it is drawn, so a change\n'
     '// of theme is one more draw.\n'
     'window.addEventListener("stratum:theme", () => { keySig = ""; draw(); });\n', 1),
    # in FracView (the product) this view is called Sequential
    ("<title>FracView — Carmine's Lab</title>", "<title>Sequential — Carmine's Lab</title>", 1),
    ('<div class="wordmark">FracView</div>', '<div class="wordmark">Sequential</div>', 1),
    ("Pick a well in the Lab — FracView follows whatever is selected there.",
     "Pick a well — Sequential follows the well and stage open beside it.", 2),
]

STACKED = [
    ("</style>", THEME_CSS, 1),
    THEME_JS,
    PICKER,
    # getters, not constants, so they are read as each chart is drawn
    ('const C = { grid: "#e3e5e8", axisText: "#697077", crosshair: "#b6bcc4",\n'
     '            ink: "#14181d", mut: "#697077" };',
     f'const C = {{ get grid() {{ return {th("#e3e5e8", "#1b2f3b")}; }}, get axisText() {{ return {th("#697077", "#93adb9")}; }},\n'
     f'            get crosshair() {{ return {th("#b6bcc4", "#9fb7c4")}; }},\n'
     f'            get ink() {{ return {th("#14181d", "#e7f4fa")}; }}, get mut() {{ return {th("#697077", "#93adb9")}; }} }};', 1),
    pair("rgba(105,112,119,0.13)", "rgba(147,173,185,0.12)", 1),
    pair("rgba(163,22,49,0.13)", "rgba(255,122,138,0.12)", 1),
    pair("#a31631", "#ff7a8a", 1),
    # and draws again when the theme changes. The curves' own colours come
    # with the stage from wellview.js, which sends it again then.
    ('  rz = setTimeout(() => { layout(); }, 120);\n});\n',
     '  rz = setTimeout(() => { layout(); }, 120);\n});\n'
     '// STRATUM PATCH (theme): the grid and text are picked as they are drawn, so\n'
     '// a change of theme is one more draw; the page embedding this one sends the\n'
     '// stage again with its curves in the new theme\'s colours.\n'
     'window.addEventListener("stratum:theme", () => drawAll());\n', 1),
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
