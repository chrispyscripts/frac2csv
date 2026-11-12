# wellsight_convert (vendored)

These three files are wellsight-convert's decoder and LAS writers, copied
**unchanged** so a fix there can be copied over again:

| File | From | sha1 when copied |
|---|---|---|
| `wellsight.py` | wellsight-convert (`TOOL = 'wellsight-convert 1.4'`) | 51ab467f811630d1fe4b7c4510e1165d9b438896 |
| `convert.py` | same | 0fc0cf72fadcb909d9c9a073e684335117f24b53 |
| `export_las.py` | `export_las 1.0` | 3a338d9e694eb34c31f7b5f51ff30485ae4f374b |

Copied 2026-11-12 from `~/Documents/Chris Vault/wellsight-convert/`.

They are standard library only, and they import each other as top-level
modules (`import wellsight`, `import convert`). `wellsight_app.py` puts this
folder on `sys.path`, and the Windows build passes
`--paths wellsight_convert` with hidden imports for all three so PyInstaller
packs them.

To update: copy the three files over, update the hashes above, and run
`python3 -m unittest tests.test_wellsight_app` with the WellSight drive
mounted (or `F2C_WS_SAMPLES` pointing at a folder of logs).

What Frac2CSV adds around them lives at the top level:
`wellsight_app.py` (one dropped file to LAS + what the Lab draws),
`wellsight_print.py` (a LogViewer printout stitched into one strip on the
LAS depth scale), `wellsight_logviewer.py` (prints with the LogViewer
installed on the PC, Windows) and `wellsight_server.py` (the local app's
endpoints).
