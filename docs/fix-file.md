# Fix file: stage numbers, dates and times a report does not print

Some reports leave out what the export needs. 00570 (AER Duvernay) prints no
date on any chart, and a few files print no stage number on a page or two. A
fix file gives the app those values. It is a plain text file with one line
per stage.

## Where it goes

- **File list (.txt) or folder:** save it beside the report, with the report's
  name and `.fix.txt` on the end. For example,
  `00570-100031806320W500_0486907_COMP.fix.txt` goes beside
  `00570-100031806320W500_0486907_COMP.pdf`.
- **Dragging PDFs into the Lab:** drop the fix file together with its report,
  in the same drop.

## What goes in it

    # stage, date, time, page
    1, 2018-09-03, 00:14
    2, 2018-09-03
    3, 2018-09-04, 04:28
    7, , , p154

- **stage:** the stage as the app names it, such as `1`, `12`, `1.2` or `3A`.
- **date:** `2018-09-03`. The app also accepts `2018/09/03`, `03-Sep-2018` and
  `Sep 3 2018`.
- **time:** optional, 24-hour, `HH:MM` or `HH:MM:SS`. It is the time at the
  chart's left edge.
- **page:** optional, such as `p154`. It is the PDF page that charts this
  stage, for a page that prints no stage number of its own.

Blank lines and anything after `#` are ignored. A field left empty keeps
what the app read. The extraction notes say how many charts the file changed
and list any line the app could not understand. Each changed chart also
carries a "from the fix file" note.
