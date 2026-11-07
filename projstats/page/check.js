// #check: recompute Python's reference numbers in the browser and list any
// mismatch. Open the page with "#check" in the address to run it.

PS.onStart(() => {
  if (!PS.state.check) return;
  const data = PS.data;
  const ref = data.reference;
  const gap = data.settings.return_gap_days;
  const rules = {core: data.settings.core_quarters, regular: data.settings.regular_quarters};
  const results = [];

  function rowsOf(kinds) {
    const allowed = data.kinds.map(k => !kinds || kinds.includes(k));
    const rows = [];
    for (let i = 0; i < data.activity.kind.length; i++) if (allowed[data.activity.kind[i]]) rows.push(i);
    return rows;
  }

  // got, want: lists of rows, compared as JSON one row at a time.
  function compare(name, got, want) {
    const diffs = [];
    for (let i = 0; i < Math.max(got.length, want.length); i++) {
      const a = JSON.stringify(got[i]);
      const b = JSON.stringify(want[i]);
      if (a !== b) diffs.push(`  page   ${a}\n  python ${b}`);
    }
    results.push({name, ok: diffs.length === 0, detail: diffs.slice(0, 5).join("\n")});
  }

  const kindsName = kinds => (kinds ? kinds.join("+") : "all kinds");

  for (const want of ref.period_counts) {
    const got = PS.metrics.periodCounts(rowsOf(want.kinds), data, PS.periodScheme(want.period), gap)
      .map(r => [r.label, r.active, r.new, r.returning, r.continuing, r.lastSeen, r.activity, r.partial]);
    compare(`period counts: ${kindsName(want.kinds)} by ${want.period}`, got, want.rows);
  }

  for (const want of ref.segments) {
    const {stats} = PS.metrics.personStats(rowsOf(want.kinds), data, rules, gap);
    const counts = {};
    for (const s of stats) {
      const [n, current] = counts[s.segment] || [0, 0];
      counts[s.segment] = [n + 1, current + (s.current ? 1 : 0)];
    }
    const sorted = Object.keys(counts).sort().map(k => [k, ...counts[k]]);
    const expected = Object.keys(want.segments).sort().map(k => [k, ...want.segments[k]]);
    compare(`segments: ${kindsName(want.kinds)}`, sorted, expected);
  }

  const {stats, dataEnd} = PS.metrics.personStats(rowsOf(null), data, rules, gap);
  const cohorts = PS.metrics.cohorts(stats, dataEnd)
    .map(c => [c.year, c.size, c.oneTime, ...PS.metrics.COHORT_OFFSETS.map(n => c.after[n])]);
  compare("cohorts: all kinds", cohorts, ref.cohorts);

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
