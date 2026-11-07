// #check: recompute Python's reference numbers in the browser and list any
// mismatch. Open the page with "#check" in the address to run it.

PS.onStart(() => {
  if (!PS.state.check) return;
  const data = PS.data;
  const ref = data.reference;
  const results = [];

  for (const want of ref.period_counts) {
    const kinds = want.kinds || data.kinds;
    const allowed = data.kinds.map(k => kinds.includes(k));
    const rows = [];
    for (let i = 0; i < data.activity.kind.length; i++) if (allowed[data.activity.kind[i]]) rows.push(i);
    const got = PS.metrics.periodCounts(rows, data, PS.periodScheme(want.period),
      data.settings.return_gap_days)
      .map(r => [r.label, r.active, r.new, r.returning, r.continuing, r.lastSeen, r.activity, r.partial]);
    const name = `period counts: ${want.kinds ? want.kinds.join("+") : "all kinds"} by ${want.period}`;
    const diffs = [];
    const n = Math.max(got.length, want.rows.length);
    for (let i = 0; i < n; i++) {
      const a = JSON.stringify(got[i]);
      const b = JSON.stringify(want.rows[i]);
      if (a !== b) diffs.push(`  page   ${a}\n  python ${b}`);
    }
    results.push({name, ok: diffs.length === 0, detail: diffs.slice(0, 5).join("\n")});
  }

  const passed = results.filter(r => r.ok).length;
  const box = PS.el("div", {class: "box"},
    PS.el("span", {class: passed === results.length ? "ok" : "bad"},
      `#check: ${passed} of ${results.length} match Python`),
    ...results.map(r => PS.el("div", {},
      `${r.ok ? "match" : "MISMATCH"}: ${r.name}`,
      r.ok ? null : PS.el("pre", {}, r.detail))));
  document.getElementById("check-panel").replaceChildren(box);
  console.log(`#check: ${passed} of ${results.length} match`, results);
});
