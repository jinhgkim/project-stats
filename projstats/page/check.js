// #check: recompute Python's reference numbers in the browser and list any
// mismatch. Open the page with "#check" in the address to run it.

PS.onStart(() => {
  if (!PS.state.check) return;
  const data = PS.data;
  const ref = data.reference;
  const gap = data.settings.return_gap_days;
  const rules = {core: data.settings.core_share, regular: data.settings.regular_share};
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

  // Theme shares per covered release cycle (to 6 decimals, as exported) and
  // trend labels.
  if (ref.theme_trends) {
    const r = PS.metrics.themeTrends(rowsOf(null), data, PS.periodScheme("release"), {skipInProgress: true});
    const name = t => data.themes.name[t];
    const round = v => Math.round(v * 1e6) / 1e6;
    const close = (a, b) => Math.abs(a - b) < 2e-6;
    const got = r.periods.filter(p => p.covered).map(p => [p.label,
      p.themes.map(s => [name(s.theme), s.share]).sort((a, b) => a[0].localeCompare(b[0]))]);
    const want = ref.theme_trends.periods.map(p => [p.label,
      Object.entries(p.shares).sort((a, b) => a[0].localeCompare(b[0]))]);
    // Shares were rounded in Python; equal within rounding counts as a match.
    for (let i = 0; i < Math.min(got.length, want.length); i++) {
      if (got[i][0] !== want[i][0] || got[i][1].length !== want[i][1].length) continue;
      got[i][1] = got[i][1].map(([t, s], k) => [t, close(s, want[i][1][k][1]) ? want[i][1][k][1] : round(s)]);
    }
    compare("theme shares by release", got, want);
    const labels = [...r.trends].map(([t, x]) => [name(t), x.label]).sort((a, b) => a[0].localeCompare(b[0]));
    compare("theme trend labels", labels,
      Object.entries(ref.theme_trends.labels).sort((a, b) => a[0].localeCompare(b[0])));
  }

  for (const want of ref.merge_times || []) {
    const got = PS.metrics.mergeTimes(rowsOf(null), data, PS.periodScheme(want.period))
      .map(r => [r.label, ...r.counts, r.median, r.partial]);
    compare(`time to merge by ${want.period}`, got, want.rows);
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
