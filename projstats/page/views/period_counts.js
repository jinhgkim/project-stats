// View: contributors per period. Stacked columns of new / returning /
// continuing people (together: everyone active). Choosing a column lists its
// people under those three groups.

// A date range that starts or ends inside a period leaves it partial too.
// metrics marks the period holding the data's end; a range that ends earlier
// leaves that period out, so its mark is cleared.
function markRangeCuts(periods, scheme, state, data) {
  const lo = state.from ? PS.dateToDay(state.from) : null;
  const hi = state.to ? PS.dateToDay(state.to) : null;
  if (lo === null && hi === null) return;
  const first = Math.min(...Object.values(data.sources));
  const end = data.project.data_end;
  for (const p of periods) {
    if (hi !== null && hi < end) p.partial = false;
    const [start, stop] = scheme.bounds(p.key);
    p.cut = (lo !== null && lo > Math.max(start === null ? -Infinity : start, first)) ||
      (hi !== null && hi < Math.min(stop === null ? Infinity : stop - 1, end));
  }
}

PS.registerView({
  id: "period-counts",
  title: "Contributors per period",
  tab: "overview",
  order: 10,
  render(figure, {data, rows, state, set}) {
    const gap = data.settings.return_gap_days;
    const scheme = PS.periodScheme(state.period);
    const periods = PS.metrics.periodCounts(rows, data, scheme, gap);
    markRangeCuts(periods, scheme, state, data);
    const partial = p => p.partial || p.cut;
    const ranged = Boolean(state.from || state.to);

    figure.subtitle.textContent =
      `How many people contribute each ${scheme.name}, and are they newcomers, returners, or regulars?`;
    PS.fillHowto(figure, [
      `Each column: everyone active in that ${scheme.name}, split three ways.`,
      `New: first activity${ranged ? " within the selected dates" : ""}. ` +
        `Returning: back after ${gap}+ days away. Continuing: everyone else.`,
      `Last seen (hover, table): people whose final activity is in that ${scheme.name}; ` +
        `unknown for the last ${gap} days, since recent people may return.`,
      `Click a column to list its people.`,
      "Faded columns are partial: the period is running, or the date range cuts it.",
      "Vertical lines: where a kind of data starts (e.g. reviews in 2016), so a jump there isn't growth.",
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
    const toggle = p => set({pick: picked === p ? undefined : `${scheme.kind}:${p.key}`});

    if (!periods.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No activity matches the filters."));
      return;
    }

    const width = Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
    const height = 320;
    const top = 36, bottom = 26, left = 40;
    const innerH = height - top - bottom;
    const yMax = d3.max(periods, p => p.active) || 1;
    const y = d3.scaleLinear([0, yMax], [innerH, 0]).nice();

    // Direct labels for the last column, where they fit; the right margin is
    // sized to the longest one. On narrow screens they drop the suffix, then
    // go entirely (the legend names the colors), so the plot keeps its width.
    const last = periods[periods.length - 1];
    const suffix = last.cut ? " (partial)" : last.partial && scheme.soFar ? " (so far)" : "";
    const labelsFor = suffix => {
      const out = [];
      let base = 0;
      for (const s of series) {
        const v = last[s.id];
        if (v > 0 && y(base) - y(base + v) >= 14) {
          out.push({y: y(base + v / 2), text: `${s.name} ${v}${suffix}`});
        }
        base += v;
      }
      return out;
    };
    const space = list => 16 + Math.max(0, ...list.map(d => PS.textWidth(d.text, 12)));
    const direct = [labelsFor(suffix), labelsFor("")].find(l => space(l) <= width * 0.22) || [];
    const right = space(direct);
    const margin = {top, right, bottom, left};
    const innerW = width - margin.left - margin.right;

    const x = d3.scaleBand(periods.map(p => p.key), [0, innerW]).paddingInner(0.25).paddingOuter(0.1);
    const barW = Math.max(1, Math.min(24, x.bandwidth()));
    const barX = p => x(p.key) + (x.bandwidth() - barW) / 2;
    const cx = p => x(p.key) + x.bandwidth() / 2;

    const svg = d3.create("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("height", height)
      .attr("role", "group")
      .attr("aria-label", `Contributors per ${scheme.name}. Arrow keys move between ` +
        `periods; the Table button shows the numbers.`);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    g.append("g").attr("class", "grid")
      .selectAll("line").data(y.ticks(5)).join("line")
      .attr("x1", 0).attr("x2", innerW).attr("y1", d => y(d)).attr("y2", d => y(d));
    g.append("g").attr("class", "axis")
      .call(d3.axisLeft(y).ticks(5, "~s").tickSize(0).tickPadding(6))
      .call(a => a.select(".domain").remove());

    // Show as many x labels as fit, about 56px apart.
    const every = Math.max(1, Math.ceil(56 / x.step()));
    const ticks = periods.filter((p, i) => i % every === 0).map(p => p.key);
    const byKey = new Map(periods.map(p => [p.key, p]));
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickValues(ticks).tickSize(0).tickPadding(8)
        .tickFormat(k => byKey.get(k).short));

    // Stacked columns: a 2px surface gap between segments, 4px round on top.
    const topRounded = (x0, y0, w, h, r) => {
      r = Math.min(r, h, w / 2);
      return `M${x0},${y0 + h}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}` +
        `H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + h}Z`;
    };
    const bars = g.append("g");
    for (const p of periods) {
      const parts = series.filter(s => p[s.id] > 0);
      let base = 0;
      parts.forEach((s, i) => {
        const bottom = y(base) - (i === 0 ? 0 : 1);
        const top = y(base + p[s.id]) + (i === parts.length - 1 ? 0 : 1);
        base += p[s.id];
        const h = bottom - top;
        if (h <= 0) return;
        const shape = i === parts.length - 1
          ? bars.append("path").attr("d", topRounded(barX(p), top, barW, h, 4))
          : bars.append("rect").attr("x", barX(p)).attr("y", top).attr("width", barW).attr("height", h);
        shape.attr("fill", s.color).attr("opacity", partial(p) ? 0.45 : 1);
      });
    }

    // Data-source markers: where an included kind's data starts.
    const markers = PS.sourceMarkers(PS.selectedKinds())
      .map(m => ({...m, key: scheme.key(m.day)}))
      .filter(m => byKey.has(m.key) && m.key !== periods[0].key);
    const markerG = g.append("g").attr("class", "marker");
    markers.forEach((m, i) => {
      markerG.append("line").attr("x1", x(m.key)).attr("x2", x(m.key))
        .attr("y1", -32 + i * 14).attr("y2", innerH);
    });
    PS.markerLabels(markerG, markers, x, -24, -margin.left, innerW + margin.right);

    for (const d of direct) {
      g.append("text").attr("class", "label")
        .attr("x", barX(last) + barW + 6).attr("y", d.y).attr("dominant-baseline", "middle")
        .text(d.text);
    }

    // Hover and focus: each period's full column is its hit target. The chart
    // is one tab stop; arrow keys, Home, and End move between periods.
    if (!byKey.has(figure.focusKey)) figure.focusKey = last.key;
    const hit = g.append("g");
    const hits = [];
    periods.forEach(p => {
      const show = event => PS.showTooltip(event, `${p.label}${partial(p) ? " (partial)" : ""}`, [
        {name: "active", value: p.active},
        ...series.map(s => ({name: s.name.toLowerCase(), value: p[s.id], color: s.color})),
        {name: "last seen", value: p.lastSeen === null ? "not known yet" : p.lastSeen},
        {name: "activity", value: p.activity},
      ]);
      hits.push(hit.append("rect").attr("class", "hit clickable")
        .attr("x", x(p.key) - (x.step() - x.bandwidth()) / 2).attr("y", 0)
        .attr("width", x.step()).attr("height", innerH)
        .attr("role", "button")
        .attr("aria-label", `${p.label}${partial(p) ? " (partial)" : ""}: ${p.active} active, ` +
          `${p.new} new, ${p.returning} returning, ${p.continuing} continuing, ` +
          `last seen ${p.lastSeen === null ? "not known yet" : p.lastSeen}. ` +
          `Press Enter to ${p === picked ? "close the list" : "list them"}.`)
        .on("pointermove", show)
        .on("focus", event => { figure.focusKey = p.key; show(event.currentTarget); })
        .on("pointerleave blur", PS.hideTooltip)
        .on("click", () => {
          toggle(p);
          if (!figure.details.hidden) figure.details.scrollIntoView({behavior: "smooth", block: "nearest"});
        })
        .on("keydown", event => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          figure.refocus = true;
          figure.focusKey = p.key;
          toggle(p);
        }).node());
    });
    PS.rovingFocus(hits, periods.findIndex(p => p.key === figure.focusKey), "ArrowLeft", "ArrowRight");

    if (picked) {
      g.append("rect").attr("x", x(picked.key) - (x.step() - x.bandwidth()) / 2).attr("y", 0)
        .attr("width", x.step()).attr("height", innerH).attr("rx", 3)
        .attr("fill", "none").attr("stroke", "var(--text-primary)").attr("stroke-width", 1.5)
        .attr("pointer-events", "none");
    }

    figure.plot.replaceChildren(svg.node());
    if (figure.refocus) {
      figure.refocus = false;
      hits[periods.findIndex(p => p.key === figure.focusKey)].focus();
    }

    if (picked === null) return;
    const name = `${picked.label}${partial(picked) ? " (partial)" : ""}`;
    const close = PS.el("button", {type: "button"}, "Close");
    close.onclick = () => set({pick: undefined});
    const group = s => {
      const members = picked.people.filter(m => m.kind === s.id)
        .sort((a, b) => b.activity - a.activity || PS.personName(a.person).localeCompare(PS.personName(b.person)));
      return PS.el("section", {class: "group"},
        PS.el("h4", {}, PS.swatch({color: s.color, shape: "rect"}), `${s.name} · ${members.length}`),
        members.length
          ? PS.el("ul", {}, members.map(m => PS.el("li", {},
            PS.personLink(m.person), PS.el("span", {class: "count"}, m.activity.toLocaleString("en-US")))))
          : PS.el("p", {class: "empty"}, "No one"));
    };
    figure.details.replaceChildren(
      PS.el("div", {class: "details-head"},
        PS.el("h3", {}, `${name} · ${picked.active} ${picked.active === 1 ? "person" : "people"}`),
        close),
      PS.el("p", {class: "meta"}, "Most active first; the number is each person's activity in this " + scheme.name + "."),
      PS.el("div", {class: "groups"}, series.map(group)));
  },
});
