// Save the seconds CSV of every well a Lab tab has ALREADY analysed, without
// re-analysing — for a tab opened before the Lab kept its results cache.
//
// In that tab: View → Developer → JavaScript Console (Cmd+Opt+J), paste this
// whole file, press Return. A box at the bottom-left counts the files as
// they land; the rows in the file list show it too. Files go where the
// Export button puts them: a destination set in Settings, else beside the
// PDF, else (read-only drive) ~/Downloads.
(async () => {
  const XLSX_TOO = false;                    // true: also the .xlsx (slow, ~20 s a well)
  const list = entries.filter(e => e.well && e.well.stages && e.well.stages.length);
  const dirOf = p => String(p).replace(/[\/\\][^\/\\]*$/, "");
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:9999;background:#17222e;"
    + "color:#fff;padding:10px 14px;border-radius:8px;font:13px/1.4 -apple-system,sans-serif;max-width:70vw";
  document.body.appendChild(box);
  const ok = [], bad = [];
  const post = async (folder, name, body) => {
    const r = await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ folder, name, destFolder: (window.settings && settings.destFolder) || "" }, body)) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j.written;
  };
  for (let i = 0; i < list.length; i++) {
    const e = list[i];
    const base = (e.well.base || e.name.replace(/\.pdf$/i, "")) + "-seconds";
    box.textContent = `saving ${i + 1}/${list.length}: ${base}.csv`;
    if (e.set) e.set(`saving ${base}.csv…`);
    await new Promise(r => setTimeout(r, 0));
    const folder = e._outDir || (e._srcPath ? dirOf(e._srcPath) : "");
    try {
      ok.push(await post(folder, base + ".csv", { text: wellCSV(e.well.stages, e.name) }));
      if (XLSX_TOO)
        ok.push(await post(folder, base + ".xlsx", { b64: b64enc(wellXLSX(e.well.stages, settings.xlsxTabs)) }));
      if (e.set) e.set(`✓ saved → ${dirOf(ok[ok.length - 1])}`, "ok");
    } catch (err) {
      bad.push(base + ": " + err.message);
      if (e.set) e.set("✗ " + err.message, "err");
    }
  }
  const dirs = [...new Set(ok.map(dirOf))];
  box.textContent = `done: ${ok.length} file(s) → ${dirs.join(", ") || "(none)"}`
    + (bad.length ? ` · ${bad.length} failed: ${bad.join("; ")}` : "");
  console.log("saved", ok, "failed", bad);
})();
