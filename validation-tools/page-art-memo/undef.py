"""Flag names a function reads but nothing in scope ever binds.

Written for one bug class: this branch renames a local `drawings` to `art`
inside a dozen readers, and a rename that lands in a function body but not on
the binding leaves a name that only fails when that page type is read — which
for a provider nobody has a test for means silence, not a crash.

usage: undef.py <tree-root> [more-roots...]
"""
import ast, builtins, os, sys

BUILTINS = set(dir(builtins))


class Scope:
    def __init__(self, parent=None):
        self.parent, self.names = parent, set()

    def bind(self, n):
        self.names.add(n)

    def known(self, n):
        s = self
        while s:
            if n in s.names:
                return True
            s = s.parent
        return False


def _iter(node):
    """Walk a statement WITHOUT entering a nested function or class body —
    those are their own scope, and letting them leak was what hid the very
    bug this script was written to find."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                continue          # its name is bound below, its body is not
            stack.append(child)


def bound_by(node):
    """Every name this statement binds in the CURRENT scope."""
    out = set()

    def tgt(t):
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                tgt(e)
        elif isinstance(t, ast.Starred):
            tgt(t.value)

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    for n in _iter(node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                tgt(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For,
                            ast.AsyncFor, ast.comprehension)):
            tgt(n.target)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            tgt(n.optional_vars)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, ast.NamedExpr):
            tgt(n.target)
        elif isinstance(n, ast.Lambda):
            out.update(params(n))
    return out


def params(fn):
    a = fn.args
    out = [p.arg for p in list(a.args) + list(a.kwonlyargs)]
    out += [p.arg for p in getattr(a, "posonlyargs", [])]
    if a.vararg:
        out.append(a.vararg.arg)
    if a.kwarg:
        out.append(a.kwarg.arg)
    return out


def check_fn(fn, parent, path, issues):
    sc = Scope(parent)
    for p in params(fn):
        sc.bind(p)
    for st in fn.body:
        sc.names |= bound_by(st)
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn:
            check_fn(n, sc, path, issues)
    # names read directly in this function, skipping nested function bodies
    skip = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn:
            for s in ast.walk(n):
                skip.add(id(s))
    for n in ast.walk(fn):
        if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                and id(n) not in skip):
            if not sc.known(n.id) and n.id not in BUILTINS:
                issues.append((path, n.lineno, fn.name, n.id))


def check(path, issues):
    try:
        tree = ast.parse(open(path, errors="replace").read())
    except SyntaxError:
        return
    mod = Scope()
    for st in tree.body:
        mod.names |= bound_by(st)
    for n in tree.body:
        for sub in ast.walk(n):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if sub is n or True:
                    pass
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_fn(n, mod, path, issues)


for root in sys.argv[1:]:
    issues = []
    seen = set()
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", "tests")]
        for f in sorted(files):
            if f.endswith(".py"):
                check(os.path.join(dirpath, f), issues)
    # dedupe: the nested walk can visit a function twice
    uniq = []
    for it in issues:
        if it not in seen:
            seen.add(it)
            uniq.append(it)
    print(f"=== {root}: {len(uniq)} undefined-name read(s) ===")
    for p, ln, fn, name in uniq:
        print(f"  {os.path.relpath(p, root)}:{ln}  in {fn}()  ->  {name}")
