"""The one-parse-per-page memo, and the rename that came with it.

frac_core.drawings() replaced thirteen page.get_drawings() calls per page.
Four readers already held a local called `drawings`, which the import now
shadows, so those locals were renamed to `art` — and in sanjel.py the rename
landed in the BODY of _gridlines but not on its parameter, leaving

    def _gridlines(drawings):        # bound
        for d in art:                # read, never bound  -> NameError

with the call site passing the imported function rather than the list. The
whole suite stayed green: nothing covered Sanjel's chart path, and pipeline
catches a failed chart into a note, so every Sanjel filing would have come
back with no chart data and no error — the exact symptom the comment above
pipeline's sanjel branch says was already paid for once.

No PDFs here, so these run with the corpus drives unplugged.
"""
import ast
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frac_core as fc            # noqa: E402
import sanjel                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every module converted to the memo
CONVERTED = ["frac_core", "lib1", "halliburton_ifs", "slb", "bj1", "canyon",
             "sanjel", "sanjel_tables", "step_vec", "leucrotta",
             "calfrac_scan", "ogc_datacapture", "pipeline"]


def _rule(x0, y0, x1, y1):
    """One stroked line, shaped like what get_drawings returns."""
    class P(object):
        def __init__(self, x, y):
            self.x, self.y = x, y
    return {"type": "s", "color": (0, 0, 0), "items": [("l", P(x0, y0),
                                                        P(x1, y1))]}


class GridlinesReadsItsArgument(unittest.TestCase):
    """sanjel._gridlines must read the list it is handed."""

    def test_finds_the_rules_it_is_given(self):
        art = ([_rule(20, y, 700, y) for y in (100.0, 200.0, 300.0)]
               + [_rule(x, 50, x, 400) for x in (20.0, 360.0, 700.0)])
        xs, ys = sanjel._gridlines(art)
        # horizontal rules -> ys, vertical -> xs; three of each, and the
        # frame is the outermost pair on each list.
        self.assertEqual(len(ys), 3, ys)
        self.assertEqual(len(xs), 3, xs)
        self.assertEqual((xs[0], xs[-1]), (20.0, 700.0))
        self.assertEqual((ys[0], ys[-1]), (100.0, 300.0))

    def test_empty_art_is_not_an_error(self):
        xs, ys = sanjel._gridlines([])
        self.assertEqual((xs, ys), ([], []))


class NoReaderReadsAnUnboundName(unittest.TestCase):
    """The rename hazard, checked across every converted reader.

    Deliberately narrow: only `art` and `drawings`, the two names this change
    moves around. A general undefined-name check would need a real scope
    resolver and would drown this in closure false positives.
    """

    def test_art_and_drawings_are_always_bound_before_they_are_read(self):
        bad = []
        for mod in CONVERTED:
            path = os.path.join(ROOT, mod + ".py")
            tree = ast.parse(open(path).read())
            top = _bound_at_module_level(tree)
            for fn in [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                bound = set(_params(fn)) | _bound_in_body(fn)
                for n in ast.walk(fn):
                    if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                            and n.id in ("art", "drawings")
                            and n.id not in bound and n.id not in top):
                        bad.append(f"{mod}.py:{n.lineno} {fn.name}() reads "
                                   f"unbound {n.id!r}")
        self.assertEqual(bad, [], "; ".join(bad))


def _params(fn):
    a = fn.args
    out = [p.arg for p in list(a.args) + list(a.kwonlyargs)
           + list(getattr(a, "posonlyargs", []))]
    if a.vararg:
        out.append(a.vararg.arg)
    if a.kwarg:
        out.append(a.kwarg.arg)
    return out


def _targets(t, out):
    if isinstance(t, ast.Name):
        out.add(t.id)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            _targets(e, out)
    elif isinstance(t, ast.Starred):
        _targets(t.value, out)


def _bound_in_body(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                _targets(t, out)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For,
                            ast.comprehension, ast.NamedExpr)):
            _targets(n.target, out)
    return out


def _bound_at_module_level(tree):
    out = set()
    for st in tree.body:
        if isinstance(st, ast.Assign):
            for t in st.targets:
                _targets(t, out)
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            for a in st.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            out.add(st.name)
    return out


class _Page(object):
    """The parts of a fitz.Page the memo keys on."""

    def __init__(self, parent, number, art):
        self.parent, self.number, self._art = parent, number, art
        self.calls = 0

    def get_drawings(self):
        self.calls += 1
        return self._art


class _Stub(object):
    """A page with no .parent/.number, as several tests hand the readers."""

    def __init__(self, art):
        self._art, self.calls = art, 0

    def get_drawings(self):
        self.calls += 1
        return self._art


class Memo(unittest.TestCase):
    def setUp(self):
        fc.forget_drawings()

    def tearDown(self):
        fc.forget_drawings()

    def test_same_page_parses_once(self):
        doc = object()
        p = _Page(doc, 7, ["a"])
        for _ in range(13):
            self.assertEqual(fc.drawings(p), ["a"])
        self.assertEqual(p.calls, 1)

    def test_next_page_replaces_the_memo(self):
        doc = object()
        a, b = _Page(doc, 1, ["one"]), _Page(doc, 2, ["two"])
        self.assertEqual(fc.drawings(a), ["one"])
        self.assertEqual(fc.drawings(b), ["two"])
        self.assertEqual(fc.drawings(a), ["one"])
        self.assertEqual(a.calls, 2)      # memo is one page deep, by design

    def test_same_page_number_in_a_different_document(self):
        d1, d2 = object(), object()
        a, b = _Page(d1, 3, ["doc1"]), _Page(d2, 3, ["doc2"])
        self.assertEqual(fc.drawings(a), ["doc1"])
        self.assertEqual(fc.drawings(b), ["doc2"])

    def test_a_stub_without_a_page_number_is_never_cached(self):
        s = _Stub(["x"])
        fc.drawings(s)
        fc.drawings(s)
        self.assertEqual(s.calls, 2)

    def test_one_thread_never_sees_another_threads_page(self):
        """The memo is thread-local because localapp reads whole documents in
        threads and fitz drops the GIL. Shared, this hands one reader another
        file's geometry — not a slow read, a wrong one."""
        wrong = []
        barrier = threading.Barrier(4)

        def run(tag):
            doc = object()
            pages = [_Page(doc, i, [f"{tag}-{i}"]) for i in range(4)]
            barrier.wait()
            for _ in range(50):
                for i, pg in enumerate(pages):
                    got = fc.drawings(pg)
                    if got != [f"{tag}-{i}"]:
                        wrong.append((tag, i, got))

        ts = [threading.Thread(target=run, args=(t,)) for t in "ABCD"]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
