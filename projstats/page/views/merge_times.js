// View: time to merge. Stacked columns of the PRs merged each period, by how
// long they waited after being opened. Choosing a column lists its PRs,
// slowest first.

const MERGE_LIST_LIMIT = 50;

PS.registerView({
  id: "merge-times",
  title: "Time to merge",
  tab: "overview",
  order: 30,
  render(figure, {data, rowsExcept, state, set}) {
    const scheme = PS.periodScheme(state.period);
    const series = PS.metrics.MERGE_BUCKETS.map((b, i) => ({...b, index: i, color: `var(--ord-${i + 1})`}));
    // The date range picks PRs by the day they were merged.
    const lo = state.from ? PS.dateToDay(state.from) : -Infinity;
    const hi = state.to ? PS.dateToDay(state.to) : Infinity;
    const periods = PS.metrics.mergeTimes(rowsExcept("dates"), data, scheme, day => day >= lo && day <= hi);
    PS.markRangeCuts(periods, scheme, state);
    const faded = p => p.partial || p.cut;
    const nameOf = p => `${p.label}${faded(p) ? " (partial)" : ""}`;
    const days = v => (v === null ? "–" : `${v} ${v === 1 ? "day" : "days"}`);
    // Choosing a column lists only its slowest bucket's PRs (30+ days).
    const slow = series[series.length - 1];

    figure.subtitle.textContent = "How long do PRs wait before they're merged?";
    PS.fillHowto(figure, [
      `Each column: the PRs merged in that ${scheme.name}, by how long they waited after being opened, ` +
        "in whole days (UTC).",
      "The date range picks PRs by the day they were merged. PRs by bots, and PRs the project config " +
        "leaves out, aren't counted.",
      `Choose a column to list its PRs that took ${slow.name}.`,
    ]);
    PS.fillLegend(figure, series.map(s => ({...s, shape: "rect"})));
    PS.fillTable(figure, [
      {name: scheme.name[0].toUpperCase() + scheme.name.slice(1), value: nameOf},
      {name: "Merged", value: p => p.merged},
      ...series.map(s => ({name: s.name, value: p => p.counts[s.index]})),
      {name: "Median days", value: p => p.median},
    ], periods);

    // The open column is `mpick` in the URL, as `<period>:<key>`, so changing
    // the period closes it.
    const picked = periods.find(p => state.mpick === `${scheme.kind}:${p.key}`) || null;
    figure.details.hidden = picked === null;
    const toggle = p => set({mpick: picked === p ? undefined : `${scheme.kind}:${p.key}`});

    if (!PS.selectedKinds().includes("pr")) {
      figure.details.hidden = true;
      PS.charts.empty(figure, "PRs count as code activity; choose All or Code under Activity to see this.");
      return;
    }
    if (!periods.length) {
      PS.charts.empty(figure, "No merged PRs match the filters.");
      return;
    }

    const last = periods[periods.length - 1];
    const byKey = new Map(periods.map(p => [p.key, p]));
    PS.charts.columns(figure, {
      items: periods,
      key: p => p.key,
      tick: k => byKey.get(k).short,
      series,
      value: (p, s) => p.counts[s.index],
      total: p => p.merged,
      faded,
      labelSuffix: last.cut ? " (partial)" : last.partial && scheme.soFar ? " (so far)" : "",
      label: `Time to merge per ${scheme.name}. Arrow keys move between periods; the Table button shows the numbers.`,
      itemLabel: p => `${nameOf(p)}: ${p.merged} PRs merged, median ${days(p.median)}; ` +
        series.map(s => `${p.counts[s.index]} ${s.name.toLowerCase()}`).join(", ") +
        `. Press Enter to ${p === picked ? "close the list" : `list the PRs that took ${slow.name}`}.`,
      tooltip: (p, anchor) => PS.showTooltip(anchor, nameOf(p), [
        {name: "merged", value: p.merged},
        {name: "median", value: days(p.median)},
        ...series.map(s => ({name: s.name.toLowerCase(), value: p.counts[s.index], color: s.color})),
      ]),
      activate: toggle,
      picked,
    });

    if (picked === null) return;
    // The column's slow PRs, laid out like the activity panes: the title row,
    // a summary line with every bucket's count, and a sortable list (slowest
    // first) of the PRs in the slowest bucket.
    const A = data.activity;
    const rerender = () => this.render(figure, {data, rowsExcept, state, set});
    if (!figure.sort) figure.sort = {key: "days", dir: "desc"};
    const merged = p => A.day[p.row] + p.days;
    const text = {person: p => PS.personName(A.person[p.row]), item: p => data.docs.title[p.doc]};
    const number = {days: p => p.days, date: merged};
    const {key, dir} = figure.sort;
    const sign = dir === "asc" ? 1 : -1;
    const prs = picked.prs.filter(p => p.days >= slow.fewest).sort((a, b) =>
      sign * (text[key] ? text[key](a).localeCompare(text[key](b)) : number[key](a) - number[key](b)) ||
      b.days - a.days || a.doc - b.doc);
    if (figure.shownFor !== state.mpick) {
      figure.shownFor = state.mpick;
      figure.showAll = false;
    }
    const num = n => n.toLocaleString("en-US");
    const more = prs.length > MERGE_LIST_LIMIT ? PS.el("button", {type: "button"},
      figure.showAll ? "Show less" : `Show all ${num(prs.length)}`) : null;
    if (more) {
      more.onclick = () => {
        figure.showAll = !figure.showAll;
        rerender();
      };
    }
    const colorOf = p => series[PS.metrics.bucketOf(p.days)].color;
    figure.details.replaceChildren(
      PS.charts.detailsHead(`PRs that took ${slow.name} · ${nameOf(picked)}`, () => set({mpick: undefined}),
        more ? [more] : []),
      PS.el("div", {class: "legend"},
        PS.el("span", {class: "total"}, `${num(picked.merged)} ${picked.merged === 1 ? "PR" : "PRs"} · median ${days(picked.median)}`),
        series.filter(s => picked.counts[s.index]).map(s =>
          PS.el("span", {class: "key"}, PS.charts.dot(s.color), `${s.name} ${num(picked.counts[s.index])}`))),
      prs.length ? PS.charts.listTable(figure.showAll ? prs : prs.slice(0, MERGE_LIST_LIMIT), {
        sort: figure.sort,
        className: "data activity with-person",
        onSort: k => {
          figure.sort = PS.nextSort(figure.sort, k, k === "date" || k === "days");
          rerender();
        },
        columns: [
          {key: "date", label: "Merged", order: "date", cell: p => PS.dayToText(merged(p))},
          {key: "days", label: "Days", order: "count", cell: p => [PS.charts.dot(colorOf(p)), num(p.days)]},
          {key: "person", label: "Person", cell: p => PS.personName(A.person[p.row])},
          {key: "item", label: "PR", cell: p => PS.el("a", {href: PS.docUrl(p.doc)}, data.docs.title[p.doc])},
        ],
      }) : PS.el("p", {class: "empty"}, `No PRs took ${slow.name} in this ${scheme.name}.`));
  },
});
