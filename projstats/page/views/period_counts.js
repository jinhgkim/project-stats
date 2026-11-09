// View: contributors per period. Stacked columns of new / returning /
// continuing people (together: everyone active). Choosing a column lists its
// people under those three groups.

PS.registerView({
  id: "period-counts",
  title: "Contributors per period",
  tab: "overview",
  order: 10,
  render(figure, {data, rows, state, set}) {
    const gap = data.settings.return_gap_days;
    const scheme = PS.periodScheme(state.period);
    const periods = PS.metrics.periodCounts(rows, data, scheme, gap);
    PS.markRangeCuts(periods, scheme, state);
    const partial = p => p.partial || p.cut;
    const ranged = Boolean(state.from || state.to);

    figure.subtitle.textContent =
      `How many people contribute each ${scheme.name}, and are they newcomers, returners, or regulars?`;
    PS.fillHowto(figure, [
      `New: first activity${ranged ? " within the selected dates" : ""}. ` +
        `Returning: back after ${gap}+ days away. Continuing: everyone else.`,
      `Last seen (hover, table): people whose final activity is in that ${scheme.name}; ` +
        `unknown for the last ${gap} days, since recent people may return.`,
    ]);

    const series = [
      {id: "new", name: "New", color: "var(--series-1)"},
      {id: "returning", name: "Returning", color: "var(--series-2)"},
      {id: "continuing", name: "Continuing", color: "var(--series-3)"},
    ];
    PS.fillLegend(figure, series.map(s => ({...s, shape: "rect"})));
    PS.fillTable(figure, [
      {name: scheme.name[0].toUpperCase() + scheme.name.slice(1),
       value: p => p.label + (partial(p) ? " (partial)" : "")},
      {name: "Active", value: p => p.active},
      ...series.map(s => ({name: s.name, value: p => p[s.id]})),
      {name: "Last seen", value: p => p.lastSeen},
      {name: "Activity", value: p => p.activity},
    ], periods);

    // The open column is `pick` in the URL, as `<period>:<key>`, so changing
    // the period closes it.
    const picked = periods.find(p => state.pick === `${scheme.kind}:${p.key}`) || null;
    figure.details.hidden = picked === null;
    const toggle = p => set({pick: picked === p ? undefined : `${scheme.kind}:${p.key}`, who: undefined});

    if (!periods.length) {
      PS.charts.empty(figure, "No activity matches the filters.");
      return;
    }

    const last = periods[periods.length - 1];
    const byKey = new Map(periods.map(p => [p.key, p]));
    PS.charts.columns(figure, {
      items: periods,
      key: p => p.key,
      tick: k => byKey.get(k).short,
      series,
      value: (p, s) => p[s.id],
      total: p => p.active,
      faded: partial,
      labelSuffix: last.cut ? " (partial)" : last.partial && scheme.soFar ? " (so far)" : "",
      // Data-source markers: where an included kind's data starts.
      markers: PS.sourceMarkers(PS.selectedKinds())
        .map(m => ({...m, key: scheme.key(m.day)}))
        .filter(m => byKey.has(m.key) && m.key !== periods[0].key),
      label: `Contributors per ${scheme.name}. Arrow keys move between periods; the Table button shows the numbers.`,
      itemLabel: p => `${p.label}${partial(p) ? " (partial)" : ""}: ${p.active} active, ` +
        `${p.new} new, ${p.returning} returning, ${p.continuing} continuing, ` +
        `last seen ${p.lastSeen === null ? "not known yet" : p.lastSeen}. ` +
        `Press Enter to ${p === picked ? "close the list" : "list them"}.`,
      tooltip: (p, anchor) => PS.showTooltip(anchor, `${p.label}${partial(p) ? " (partial)" : ""}`, [
        {name: "active", value: p.active},
        ...series.map(s => ({name: s.name.toLowerCase(), value: p[s.id], color: s.color})),
        {name: "last seen", value: p.lastSeen === null ? "not known yet" : p.lastSeen},
        {name: "activity", value: p.activity},
      ]),
      activate: toggle,
      picked,
    });

    if (picked === null) return;
    const name = `${picked.label}${partial(picked) ? " (partial)" : ""}`;
    const group = s => {
      const members = picked.people.filter(m => m.kind === s.id)
        .sort((a, b) => b.activity - a.activity || PS.personName(a.person).localeCompare(PS.personName(b.person)));
      return PS.el("section", {class: "group"},
        PS.el("h4", {}, PS.swatch({color: s.color, shape: "rect"}), `${s.name} · ${members.length}`),
        members.length
          ? PS.el("ul", {}, members.map(m => PS.el("li", {},
            PS.personButton(m.person, state),
            PS.el("span", {class: "count"}, m.activity.toLocaleString("en-US")))))
          : PS.el("p", {class: "empty"}, "No one"));
    };
    figure.details.replaceChildren(
      PS.charts.detailsHead(`${name} · ${picked.active} ${picked.active === 1 ? "person" : "people"}`,
        () => set({pick: undefined, who: undefined})),
      PS.el("p", {class: "meta"}, "Most active first; the number is each person's activity in this " + scheme.name + "."),
      PS.el("div", {class: "groups"}, series.map(group)));
  },
});
