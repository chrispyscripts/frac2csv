"""Print a WellSight file to PDF with the LogViewer installed on this PC.

LogViewer is WellSight's free viewer. Its licence (section 5a) does not let
anyone pass the program on, so Frac2CSV does not carry a copy: it uses the one
the user installed from wellsight.com, and says so when there is none.

LogViewer has no command line for printing. It prints from File > Print, to
any Windows printer, and Windows comes with "Microsoft Print to PDF". So this
does what a person would: opens the file in LogViewer, opens File > Print,
picks All, Color and no Page Breaks (the log then runs on from page to page,
which is what wellsight_print.stitch expects), prints to Microsoft Print to
PDF, and types the output path into its Save dialog.

Windows only; needs pywinauto (in the Windows build). Every step that can go
wrong says which one it was, and the dialog's controls are written to the log
so a LogViewer that lays its Print dialog out differently can be fixed from
one log.
"""
import glob
import os
import sys
import threading
import time

PDF_PRINTER = "Microsoft Print to PDF"
DOWNLOAD = "https://www.wellsight.com"
_LOCK = threading.Lock()          # one LogViewer at a time


class LogViewerError(Exception):
    pass


def find_viewer():
    """Path to LogViewer's Viewer.exe, or None. F2C_LOGVIEWER overrides."""
    env = os.environ.get("F2C_LOGVIEWER", "").strip().strip('"')
    if env and os.path.isfile(env):
        return env
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
             os.environ.get("ProgramW6432"), r"C:\Program Files (x86)", r"C:\Program Files"]
    seen = set()
    for base in bases:
        if not base or base in seen:
            continue
        seen.add(base)
        for pat in (os.path.join(base, "WellSight Systems", "*", "Viewer.exe"),
                    os.path.join(base, "WellSight Systems", "Viewer.exe"),
                    os.path.join(base, "WellSight*", "*", "Viewer.exe")):
            hits = sorted(glob.glob(pat), reverse=True)     # LogViewer 8 before 6
            if hits:
                return hits[0]
    return None


def status():
    """What the Lab shows next to the Printout button."""
    if sys.platform != "win32":
        return {"available": False,
                "why": "LogViewer runs on Windows. Print the log there, or drop a printout PDF."}
    exe = find_viewer()
    if not exe:
        return {"available": False,
                "why": "WellSight LogViewer is not installed on this PC. It is free from "
                       f"{DOWNLOAD} (Software, LogViewer). Or drop a printout PDF."}
    return {"available": True, "viewer": exe}


def _dump(ctrl):
    """The control tree of a window, as text, for the log."""
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            ctrl.print_control_identifiers(depth=4)
    except Exception as e:  # noqa: BLE001
        return f"(could not list controls: {e})"
    return buf.getvalue()[-6000:]


def _wait_file(path, timeout):
    """Until the PDF exists and has stopped growing."""
    end = time.time() + timeout
    last = -1
    while time.time() < end:
        if os.path.exists(path):
            n = os.path.getsize(path)
            if n > 0 and n == last:
                return True
            last = n
        time.sleep(1.0)
    return False


def _plain(t):
    """A control's text as a person reads it: no '&' shortcut marks, no
    trailing '...' or ':' and no accelerator after a tab."""
    t = (t or "").split("\t")[0].replace("&", "").strip()
    return t.rstrip(".:").strip().lower()


def _find(win, text, cls=None):
    """The descendant of `win` whose text reads `text`, or None."""
    want = _plain(text)
    for c in win.descendants():
        try:
            if cls and c.friendly_class_name() != cls and c.class_name() != cls:
                continue
            if _plain(c.window_text()) == want:
                return c
        except Exception:  # noqa: BLE001
            continue
    return None


def _set_check(box, want):
    try:
        on = bool(box.get_check_state())
    except Exception:  # noqa: BLE001
        on = bool(box.is_checked())
    if on != want:
        box.click()


def _save_name_box(save):
    """The Save dialog's file-name box: control 1001 in the Vista-style
    dialog, 1152 in the old one, else the first edit inside a combo box."""
    for cid in (1001, 1152):
        try:
            e = save.child_window(control_id=cid, class_name="Edit")
            if e.exists(timeout=1):
                return e.wrapper_object()
        except Exception:  # noqa: BLE001
            pass
    for e in save.wrapper_object().descendants(class_name="Edit"):
        try:
            if e.parent().class_name() == "ComboBox":
                return e
        except Exception:  # noqa: BLE001
            continue
    return None


def print_to_pdf(native, out_pdf, timeout=240, log=None):
    """Open `native` in LogViewer and print it to `out_pdf`. Returns out_pdf.
    LogViewer's window comes up on screen while this runs; leave it be."""
    say = log or (lambda m: sys.stderr.write("[logviewer] " + m + "\n"))
    st = status()
    if not st["available"]:
        raise LogViewerError(st["why"])
    try:
        from pywinauto import Application, Desktop
    except ImportError:
        raise LogViewerError("this build cannot drive LogViewer (pywinauto missing). "
                             "Print the log from LogViewer and drop the PDF.")
    import win32print            # pywin32, which pywinauto brings
    printers = [p[2] for p in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    if PDF_PRINTER not in printers:
        raise LogViewerError(f'the "{PDF_PRINTER}" printer is not installed on this PC '
                             "(Windows Settings, Printers, Add, or Optional features).")
    out_pdf = os.path.abspath(out_pdf)
    if os.path.exists(out_pdf):
        os.remove(out_pdf)
    with _LOCK:
        step = "starting LogViewer"
        app = None
        seen = []                # windows to list in the log if a step fails
        try:
            say(f"{step}: {st['viewer']} {native}")
            app = Application(backend="win32").start(f'"{st["viewer"]}" "{native}"',
                                                     timeout=60)
            app.top_window().wait("ready", timeout=60)
            time.sleep(1.5)
            # a tip-of-the-day or notice can sit over the log
            main = None
            for w in app.windows():
                t = (w.window_text() or "").lower()
                if w.is_dialog() and ("tip" in t or "notice" in t or "welcome" in t):
                    try:
                        w.close()
                    except Exception:  # noqa: BLE001
                        pass
            main = app.top_window().wrapper_object()
            seen.append(main)
            say(f"LogViewer window: {main.window_text()!r}")

            step = "opening File > Print"
            say(step)
            try:
                main.menu_select("File->Print...")
            except Exception as e:  # noqa: BLE001
                say(f"menu File->Print... not found ({e}); trying Ctrl+P")
                main.set_focus()
                main.type_keys("^p")
            dlg = app.window(title_re=r"(?i)^print\b.*")
            dlg.wait("visible", timeout=30)
            dlg = dlg.wrapper_object()
            seen.append(dlg)
            say(f"Print dialog: {dlg.window_text()!r}")

            step = f'choosing the "{PDF_PRINTER}" printer'
            say(step)
            shown = " ".join(c.window_text() for c in dlg.descendants())
            if PDF_PRINTER not in shown:
                setup_btn = _find(dlg, "Setup", "Button")
                if setup_btn is None:
                    raise LogViewerError("no Setup button in LogViewer's Print dialog")
                setup_btn.click()
                setup = app.window(title_re=r"(?i).*(print|page) setup.*")
                setup.wait("visible", timeout=20)
                setup = setup.wrapper_object()
                seen.append(setup)
                combo = setup.descendants(class_name="ComboBox")[0]
                combo.select(PDF_PRINTER)
                ok = _find(setup, "OK", "Button")
                if ok is not None:
                    ok.click()
                else:
                    setup.type_keys("{ENTER}")
                time.sleep(1.0)

            step = "setting All, Color, no Page Breaks"
            say(step)
            for text, want in (("All", True), ("Color", True), ("Page Breaks", False),
                               ("First Page Blank", False)):
                box = _find(dlg, text, "Button")
                if box is None:
                    say(f'no "{text}" option in the Print dialog; left as it was')
                    continue
                if text == "All":
                    box.click()
                else:
                    _set_check(box, want)

            step = "printing"
            say(step)
            go = _find(dlg, "Print", "Button") or _find(dlg, "OK", "Button")
            if go is None:
                raise LogViewerError("no Print button in LogViewer's Print dialog")
            go.click()

            step = "naming the PDF in the Save dialog"
            say(step)
            save = Desktop(backend="win32").window(title_re=r"(?i)save print output as|save as")
            save.wait("visible", timeout=90)
            seen.append(save.wrapper_object())
            box = _save_name_box(save)
            if box is None:
                raise LogViewerError("could not find the file name box in the Save dialog")
            box.set_edit_text(out_pdf)
            time.sleep(0.3)
            if (box.window_text() or "").strip().lower() != out_pdf.lower():
                raise LogViewerError("the Save dialog did not take the file name")
            try:
                save.child_window(control_id=1, class_name="Button").click()
            except Exception:  # noqa: BLE001
                (_find(save.wrapper_object(), "Save", "Button") or box).click()

            step = "waiting for the PDF"
            say(step)
            if not _wait_file(out_pdf, timeout):
                raise LogViewerError(f"LogViewer did not finish the PDF in {timeout} s")
            say(f"printed {out_pdf} ({os.path.getsize(out_pdf)} bytes)")
            return out_pdf
        except Exception as e:  # noqa: BLE001
            trees = []
            for w in seen[::-1]:
                try:
                    trees.append(f"--- {w.window_text()!r}\n{_dump(w)}")
                except Exception:  # noqa: BLE001
                    pass
            try:
                for w in Desktop(backend="win32").windows():
                    t = w.window_text() or ""
                    if t and any(k in t.lower() for k in ("print", "save", "wellsight", "logviewer", "viewer")):
                        trees.append(f"--- top-level {t!r} class {w.class_name()}")
            except Exception:  # noqa: BLE001
                pass
            say(f"failed while {step}: {type(e).__name__}: {e}\n" + "\n".join(trees))
            if isinstance(e, LogViewerError):
                raise LogViewerError(f"while {step}: {e}. The details are in the Frac2CSV log.")
            raise LogViewerError(
                f"could not drive LogViewer while {step} ({type(e).__name__}). In LogViewer: "
                f"File > Print, printer {PDF_PRINTER}, All, Page Breaks off; then drop the "
                "PDF on this log. The details are in the Frac2CSV log.")
        finally:
            if app is not None:
                try:
                    app.kill(soft=True)
                except Exception:  # noqa: BLE001
                    pass
