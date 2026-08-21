"""The operator's daily report as a source of dates and clocks.

Every vendor reader here dates its charts from a sheet the VENDOR prints — a
Stimulation Service Report, a Zone Summary, a Treatment Summary grid, a Daily
Stage Summary. When that sheet is not in the document, the reader has nothing,
and that is not rare:

  - 00020 is 493 pages with no Treatment Summary grid anywhere, and its charts
    plot "Time (min)" from 0, so nothing on the vendor side can clock them.
    81 charts, every one dated, not one with a start time.
  - 00121 carries no Service Report, no Zone Summary and no Frac Stage Details
    — its PRC charts print a clock and no calendar.
  - Across the 184 pure-vector filings, 173 carry NONE of the four sheets.

The operator's daily report is the answer to all of them, and it is the same
answer because it is the same document: whoever pumped the job, the operator
files a day-by-day log, and its rows carry a start, an end, an activity code
and the stage in the comment, under the page's own report date.

    00121:  17:15 | 18:30 | 1.25 FRAC | Frac. Job | Started pumping on Stage #10.
    00020:  08:00 | 11:30 | 3.50 | 11.50 FRAC | PP  | ... | Frac Stage # 1 (...)

Same shape, one extra cumulative-hours column. So this reads rows structurally
— two clocks, then whatever, then the text up to the next row — rather than by
counting columns.

WHAT THIS IS NOT. It is a LAST RESORT, below anything the chart or the vendor
sheet says. Where a chart prints its own clock, that clock wins and this only
fills what is missing — and on 00121 the two can be compared, which is how the
lost-PM bug surfaced. Where the chart plots elapsed minutes there is nothing
to check against, so a caller taking a time from here should say so.
"""
import re

# The wordings seen so far — and the list is NOT the test, because it kept
# being wrong. 00121 says "Regulatory_Daily Completion and Workover", 00020
# "Daily Completion Operations", 00588 "Daily Completion & WS (board report)",
# 00445 "DC & Workover - WellOps Regulatory Report". Every new file found a
# fifth spelling, and 00588's 15 charts went undated for no better reason than
# a title this list had not met yet.
MARKERS = (
    "Regulatory_Daily Completion and Workover",
    "Daily Completion Operations",
    "Daily Completion and Workover",
    "Daily Completion & WS",
    "DC & Workover",
)

_REPORT_DATE = re.compile(
    r"(?i)Report\s*(?:#\s*[\d.]+,\s*)?Report\s*Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_ANY_DATE = re.compile(r"(?i)Report\s*Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_CLOCK_LINE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# The stage number, read ONLY from inside a row. A comment that ends "ready to
# Frac Stage #" is followed by the next cell — a clock — and a regex allowed to
# run past the row boundary reads "16:30" as stage 16.
# Plural too — "Frac stages # 1" is a stage mention and pretending it is not
# would leave the row looking unambiguous when it is not. See stage_times.
_STAGE = re.compile(r"(?i)stages?\s*#?\s*(\d{1,3})(?!\s*:)")
# The activity CODE, not the word. Every row's code sits on its own line with
# its hours — "1.25 FRAC", "11.50 FRAC", "0.50 ACID" — and the word "frac"
# turns up in the COMMENTS of rows that are not frac rows at all: the acid row
# on 00121 p30 ends "ready to Frac Stage #", and matching the bare word made
# that row answer for stage 10 at 16:00 when pumping began at 17:15.
# How many lines after its start clock a row's own comment can run. Comments
# are wordy but bounded; the page furniture that follows a time log is not.
_MAX_ROW_LINES = 12

_FRAC_CODE = re.compile(r"(?im)^\s*[\d.]+\s+FRAC\s*$")


def is_daily_report(text):
    """Is this page a daily operations sheet?

    Recognised by SHAPE first and title second: a page that prints a report
    date and a run of time-log rows IS a daily report whatever its heading
    says. Over-matching is cheap here — stage_times() then requires a FRAC
    code row naming a stage, so a page that merely looks like one contributes
    nothing — while under-matching costs a whole file its clocks.
    """
    # "&" and "and" are the same title. Operators print it both ways and OCR
    # picks whichever it likes, so ARC's "Daily Completion and WS (board
    # report)" missed the "Daily Completion & WS" marker by one word — and
    # then missed the shape test too, because the time-log rows on that
    # scanned page OCR as "| endtime | burt) | Code _]". lib1 read it as a
    # Liberty chart and reported a broken one.
    flat = text.replace("&", "and")
    if any(m.replace("&", "and") in flat for m in MARKERS):
        return True
    return report_date(text) is not None and len(rows(text)) >= 2


def report_date(text):
    """-> 'YYYY-MM-DD' for this daily sheet, or None."""
    m = _ANY_DATE.search(text)
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= dy <= 31 and 1990 <= yr <= 2100):
        return None
    return f"{yr:04d}-{mo:02d}-{dy:02d}"


def rows(text):
    """-> [(start_hhmm, body)] for each time-log row on the page.

    A row begins where a clock line is followed by another clock line, and
    runs to the start of the next row. Bounding the body matters more than
    parsing the columns: the stage number has to be read from THIS row and
    not from the next row's clock.
    """
    lines = text.splitlines()
    starts = []
    for i in range(len(lines) - 1):
        a = _CLOCK_LINE.match(lines[i].strip())
        b = _CLOCK_LINE.match(lines[i + 1].strip())
        if a and b:
            starts.append((i, f"{int(a.group(1)):02d}:{a.group(2)}"))
    out = []
    for n, (i, hhmm) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        # The LAST row would otherwise run to the end of the page and swallow
        # whatever follows the time log. On 00588 what follows is a period
        # summary — "Frac stages # 1, Pump Down stage # 2" — and absorbing it
        # put the PUMP-DOWN stage's number on the FRAC row's clock. A row's
        # own comment is a handful of lines; anything further down the page
        # belongs to something else.
        end = min(end, i + _MAX_ROW_LINES)
        out.append((hhmm, "\n".join(lines[i:end])))
    return out


def stage_times(text):
    """-> {stage: 'HH:MM'} from this page's FRAC rows.

    The EARLIEST frac row for a stage is the one kept: a stage is named again
    in later rows ("ready to Frac Stage #11", "Started pumping on Stage #11")
    and the first is where pumping began.
    """
    got = {}
    for hhmm, body in rows(text):
        if not _FRAC_CODE.search(body):
            continue
        found = {int(x) for x in _STAGE.findall(body)}
        # A row that names TWO stages names neither. 00588's frac row sits
        # beside "Frac stages # 1,   Pump Down stage # 2" — two stages for two
        # different operations — and taking either one puts a clock on the
        # wrong stage. This is the whole reason the row is read rather than
        # the page: when even the row is ambiguous, it has to say nothing.
        if len(found) != 1:
            continue
        stage = found.pop()
        if stage not in got or hhmm < got[stage]:
            got[stage] = hhmm
    return got


def index(doc):
    """{stage: {'date','start'}} over a whole document's daily reports.

    A stage claimed by two DIFFERENT days is dropped rather than resolved.
    An undated chart is a visible gap; a chart stamped off the wrong day is a
    wrong answer wearing a date — the same rule slb.service_report_index uses.
    """
    seen = {}
    for pno in range(doc.page_count):
        try:
            text = doc[pno].get_text()
        except Exception:
            continue
        if not is_daily_report(text):
            continue
        day = report_date(text)
        if not day:
            continue
        for stage, hhmm in stage_times(text).items():
            days = seen.setdefault(stage, {})
            days[day] = min(hhmm, days.get(day, "99:99"))
    out = {}
    for stage, days in seen.items():
        if len(days) != 1:
            continue                       # two days claim it: say nothing
        day, hhmm = next(iter(days.items()))
        out[stage] = {"date": day, "start": f"{hhmm}:00"}
    return out
