// View: how concentrated the activity is. People ranked by activity along the
// bottom, the share of all activity they add up to on the left, and the
// segments (core, regular, casual, one-time) as zones along the curve.
// Choosing a zone lists its people; the Overview tiles also open lists here.

PS.registerView({
  id: "segments",
  title: "Segments",
  tab: "people",
  order: 20,
  render(figure, {data, rows, rowsExcept, state, set}) {
    const gap = data.settings.return_gap_days;
    const rules = PS.segmentRules(state);
    const {stats, dataEnd} = PS.metrics.personStats(rows, data, rules, gap, rowsExcept("people"));
    const pctOf = v => `${Math.round(v * 100)}%`;
    const names = {core: "Core", regular: "Regular", casual: "Casual", "one-time": "One-time"};
    const zoneColor = {
      core: "var(--seq-3)", regular: "var(--seq-2)", casual: "var(--seq-1)", "one-time": "var(--wash)",
    };
    const total = stats.reduce((sum, s) => sum + s.activity, 0);
    const segments = PS.metrics.SEGMENTS.map(id => {
      const members = stats.filter(s => s.segment === id);
      const activity = members.reduce((sum, s) => sum + s.activity, 0);
      return {
        id, name: names[id], people: members.length,
        current: members.filter(s => s.current).length,
        activity, share: total ? activity / total : 0,
      };
    });

    const core = segments[0];
    const leftOut = PS.leftOutLabels(state).join(", ");
    figure.subtitle.textContent = core.people
      ? `How concentrated is the work? ${core.people} ${core.people === 1 ? "person does" : "people do"} ` +
        `${Math.round(core.share * 100)}% of the activity${leftOut ? `, not counting the ${leftOut}` : ""}.`
      : "How concentrated is the work, and how many people help out now and then?";
    PS.fillHowto(figure, [
      `Core: the fewest top people who reach ${pctOf(rules.core)}. Regular: the next, up to ${pctOf(rules.regular)}. ` +
        "Casual: everyone else with more than one activity. One-time: exactly one.",
      leftOut ? `The ${leftOut} is left out of the counts, but the groups are still drawn with everyone counted, ` +
        "so the same people stay in each one and the shares are of the activity that remains." : null,
    ].filter(Boolean));
    PS.fillLegend(figure, PS.metrics.SEGMENTS.map(id => ({name: names[id], color: zoneColor[id], shape: "rect"})));
    const pct = v => `${(v * 100).toFixed(1)}%`;
    PS.fillTable(figure, [
      {name: "Segment", value: s => s.name},
      {name: "People", value: s => s.people},
      {name: "Active now", value: s => s.current},
      {name: "Activity", value: s => s.activity},
      {name: "Share of activity", value: s => pct(s.share)},
    ], segments);

    // People lists, chosen in the URL as `list`: a segment, or the active-now
    // and new people the Overview tiles count.
    const lists = {
      ...Object.fromEntries(segments.map(x => [x.id, {title: x.name, test: p => p.segment === x.id}])),
      active: {title: `Active in the last ${gap} days`, test: p => p.current},
      new: {title: `New in the last ${gap} days`, test: p => dataEnd - p.first < gap},
    };
    // The core list is open unless the person closed it (`list=none`).
    const wanted = state.list === undefined ? "core" : state.list;
    const listId = stats.length && lists[wanted] ? wanted : null;
    figure.details.hidden = listId === null;
    const toggleList = id => set({list: listId === id ? "none" : id === "core" ? undefined : id});

    if (!stats.length) {
      PS.charts.empty(figure, "No activity matches the filters.");
      return;
    }

    const width = PS.charts.width(figure);
    const height = 300;
    const margin = {top: 40, right: 16, bottom: 46, left: 56};
    const {svg, g, innerW, innerH} = PS.charts.frame(width, height, margin,
      "Segments. Arrow keys move between zones; the Table button shows the numbers.");
    const n = stats.length;
    // Rank r sits at x(r) and spans x(r - 0.5) to x(r + 0.5).
    const x = d3.scaleLog([0.5, n + 0.5], [0, innerW]);
    const y = d3.scaleLinear([0, 1], [innerH, 0]);
    let running = 0;
    const cum = stats.map(p => { running += p.activity; return total ? running / total : 0; });
    const zones = segments.map(sg => {
      const lo = stats.findIndex(p => p.segment === sg.id);
      return {...sg, lo, hi: lo < 0 ? -1 : stats.findLastIndex(p => p.segment === sg.id)};
    }).filter(z => z.people > 0);
    const zoneX0 = z => x(z.lo + 0.5);
    const zoneW = z => x(z.hi + 1.5) - x(z.lo + 0.5);

    zones.forEach(z => g.append("rect").attr("x", zoneX0(z)).attr("y", 0).attr("width", zoneW(z))
      .attr("height", innerH).attr("fill", zoneColor[z.id]));
    PS.charts.yAxis(g, y, innerW, {values: [0, 0.25, 0.5, 0.75, 1], format: d3.format(".0%")});
    const xTicks = [1, 3, 10, 30, 100, 300, 1000, 3000].filter(t => t <= n);
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickValues(xTicks.length ? xTicks : [1]).tickFormat(v => String(v)).tickSize(0).tickPadding(8));
    g.append("text").attr("class", "label").attr("x", innerW / 2).attr("y", innerH + 38)
      .attr("text-anchor", "middle").text("People, most active first");
    g.append("text").attr("class", "label").attr("transform", "rotate(-90)")
      .attr("x", -innerH / 2).attr("y", -44).attr("text-anchor", "middle").text("Share of all activity");

    // Zone names above the plot, as many as fit.
    zones.forEach(z => {
      const cx = zoneX0(z) + zoneW(z) / 2;
      const count = `${z.people} ${z.people === 1 ? "person" : "people"}`;
      const room = zoneW(z) - 2;
      if (PS.textWidth(z.name, 12) > room) return;
      g.append("text").attr("class", z.id === listId ? "label current" : "label")
        .attr("x", cx).attr("y", -24).attr("text-anchor", "middle").text(z.name);
      if (PS.textWidth(count, 11) <= room) {
        g.append("text").attr("x", cx).attr("y", -10).attr("text-anchor", "middle").text(count);
      }
    });

    // The curve: 0 people reach 0%; each person adds their own activity.
    const points = [[0, 0], ...stats.map((p, i) => [x(i + 1), cum[i]])];
    g.append("path").datum(points)
      .attr("fill", "none").attr("stroke", "var(--text-primary)").attr("stroke-width", 2)
      .attr("stroke-linejoin", "round").attr("stroke-linecap", "round")
      .attr("d", d3.line().x(d => d[0]).y(d => y(d[1])));

    // Where core and regular end: how many people it took, and the total share.
    zones.filter(z => z.id === "core" || z.id === "regular").forEach(z => {
      const rank = z.hi + 1;
      const cx = x(rank), cy = y(cum[z.hi]);
      g.append("circle").attr("cx", cx).attr("cy", cy).attr("r", 4)
        .attr("fill", "var(--text-primary)").attr("stroke", "var(--surface-1)").attr("stroke-width", 2);
      const text = `${rank} ${rank === 1 ? "person" : "people"}: ${pct(cum[z.hi])}`;
      const w = PS.textWidth(text, 12);
      const right = cx + 8 + w <= innerW;
      g.append("text").attr("class", "label halo").attr("x", right ? cx + 8 : cx - 8).attr("y", cy + 16)
        .attr("text-anchor", right ? "start" : "end").text(text);
    });

    const picked = zones.find(z => z.id === listId);
    if (picked) PS.charts.outline(g, {x: zoneX0(picked), y: 0, width: zoneW(picked), height: innerH});

    const refocus = PS.charts.hits(figure, zones.map(z => g.append("rect").attr("class", "hit clickable")
      .attr("x", zoneX0(z)).attr("y", 0).attr("width", zoneW(z)).attr("height", innerH)), {
      keys: ["ArrowLeft", "ArrowRight"],
      current: Math.min(figure.focusRow || 0, zones.length - 1),
      label: i => {
        const z = zones[i];
        return `${z.name}: ${z.people} people, ${z.current} active now, ` +
          `${pct(z.share)} of activity. Press Enter to ${z.id === listId ? "close the list" : "list them"}.`;
      },
      show: (i, anchor) => {
        const z = zones[i];
        PS.showTooltip(anchor, z.name, [
          {name: "people", value: z.people},
          {name: "active now", value: z.current},
          {name: "activity", value: z.activity},
          {name: "share of activity", value: pct(z.share)},
        ]);
      },
      activate: i => toggleList(zones[i].id),
      onFocus: i => { figure.focusRow = i; },
    });
    figure.plot.replaceChildren(svg.node());
    refocus();

    if (listId === null) return;
    const list = lists[listId];
    const people = stats.filter(list.test);
    const listShare = total ? people.reduce((sum, p) => sum + p.activity, 0) / total : 0;
    const showSegment = !PS.metrics.SEGMENTS.includes(listId);
    // Active now is a filled dot before the name (hollow when not); activity
    // is a bar on one scale for the whole list, with the share beside it.
    const head = [["Person", "left"], ...(showSegment ? [["Segment", "left"]] : []), ["Activity", "left"],
      ["Share"], ["First"], ["Last"]];
    const day = d => PS.dayToText(d);
    const most = Math.max(1, ...people.map(p => p.activity));
    const status = on => PS.el("span", {class: on ? "status on" : "status", title: on ? "active now" : "not active now"},
      PS.el("span", {class: "sr-only"}, on ? "active now: " : "not active now: "));
    const body = people.map(p => {
      const share = pct(total ? p.activity / total : 0);
      return PS.el("tr", {},
        PS.el("td", {}, status(p.current), PS.personButton(p.person, state, "people-")),
        showSegment ? PS.el("td", {class: "left"}, p.segment) : null,
        PS.el("td", {class: "left"},
          PS.el("div", {class: "cellbar"},
            PS.el("span", {class: "num"}, p.activity.toLocaleString("en-US")),
            PS.el("span", {class: "track"},
              PS.el("span", {class: "bar", style: `width: ${(p.activity / most) * 100}%`})))),
        PS.el("td", {}, share),
        PS.el("td", {}, day(p.first)),
        PS.el("td", {}, day(p.last)));
    });
    const key = PS.el("p", {class: "status-key"},
      PS.el("span", {class: "status on", "aria-hidden": "true"}), `active in the last ${gap} days`,
      PS.el("span", {class: "status", "aria-hidden": "true"}), "not");
    figure.details.replaceChildren(
      PS.charts.detailsHead(`${list.title} · ${people.length} ${people.length === 1 ? "person" : "people"} · ` +
        `${pct(listShare)} of activity`, () => set({list: "none"})),
      key,
      people.length
        ? PS.el("div", {class: "table-wrap"},
          PS.el("table", {class: "data people"}, PS.el("thead", {}, PS.el("tr", {}, head.map(([h, cls]) => PS.el("th", {scope: "col", class: cls}, h)))),
            PS.el("tbody", {}, body)))
        : PS.el("p", {class: "empty"}, "No one matches."));
  },
});
