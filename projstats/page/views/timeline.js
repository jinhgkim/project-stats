// View: one row per person, ordered by first activity, with a mark for each
// period they were active in. Segment toggles choose who is listed.

PS.registerView({
  id: "timeline",
  title: "Timeline per person",
  tab: "people",
  order: 40,
  render(figure, {data, rows, state, set}) {
    const gap = data.settings.return_gap_days;
    const rules = PS.segmentRules(state);
    const scheme = PS.periodScheme(state.period);
    const {stats} = PS.metrics.personStats(rows, data, rules, gap);
    const ids = PS.metrics.SEGMENTS;
    const shown = new Set(state.tl === undefined ? ["core", "regular"]
      : state.tl.split(",").filter(s => ids.includes(s)));
    const counts = Object.fromEntries(ids.map(id => [id, stats.filter(s => s.segment === id).length]));

    // Segment toggles, built once and kept in step with the state.
    const names = {core: "Core", regular: "Regular", casual: "Casual", "one-time": "One-time"};
    if (!figure.toggles) {
      figure.toggles = ids.map(id => {
        const button = PS.el("button", {type: "button"});
        button.onclick = () => {
          const next = new Set(shown);
          if (next.has(id)) next.delete(id); else next.add(id);
          const list = ids.filter(s => next.has(s));
          set({tl: list.join(",") === "core,regular" ? undefined : list.join(",")});
        };
        return button;
      });
      figure.controls.append(PS.el("span", {class: "label"}, "Show"), ...figure.toggles);
    }
    figure.toggles.forEach((button, i) => {
      const label = `${names[ids[i]]} ${counts[ids[i]]}`;
      button.textContent = label;
      button.setAttribute("data-label", label);
      button.setAttribute("aria-pressed", String(shown.has(ids[i])));
    });

    const people = stats.filter(s => shown.has(s.segment))
      .sort((a, b) => a.first - b.first || PS.personName(a.person).localeCompare(PS.personName(b.person)));

    figure.subtitle.textContent = "When was each person active, and who is still around?";
    PS.fillHowto(figure, [
      "One row per person in the chosen segments, ordered by when they started.",
      `Each mark is a ${scheme.name} with activity; its shade shows how much (see the legend). ` +
        "Periods follow Group by in Contributors per period, on the Overview tab.",
      `Bold names: active in the last ${gap} days of the data shown.`,
      "Segments use the cutoffs set in Segments. Hover a row for that person's numbers.",
    ]);
    const BINS = [2, 6, 21];
    const binOf = n => BINS.filter(t => n >= t).length;
    PS.fillLegend(figure, ["1 activity", "2–5", "6–20", "21+"]
      .map((name, i) => ({name, color: `var(--ord-${i + 1})`, shape: "rect"})));
    const dayText = d => PS.dayToText(d);
    PS.fillTable(figure, [
      {name: "Person", value: s => PS.personLink(s.person)},
      {name: "Segment", value: s => s.segment},
      {name: "First", value: s => dayText(s.first)},
      {name: "Last", value: s => dayText(s.last)},
      {name: "Activity", value: s => s.activity},
      {name: "Active quarters", value: s => s.quarters},
      {name: "Returns", value: s => s.returns},
      {name: "Active now", value: s => (s.current ? "yes" : "no")},
    ], people);

    if (!people.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"},
        stats.length ? "No one in the chosen segments." : "No activity matches the filters."));
      return;
    }

    // Activity per person per period, for the people shown.
    const A = data.activity;
    const wanted = new Set(people.map(s => s.person));
    const perPerson = new Map(people.map(s => [s.person, new Map()]));
    let minKey = Infinity, maxKey = -Infinity;
    for (const i of rows) {
      const key = scheme.key(A.day[i]);
      if (key < minKey) minKey = key;
      if (key > maxKey) maxKey = key;
      if (!wanted.has(A.person[i])) continue;
      const m = perPerson.get(A.person[i]);
      m.set(key, (m.get(key) || 0) + 1);
    }
    const keys = d3.range(minKey, maxKey + 1);

    const width = Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
    const maxNameW = Math.min(170, Math.round(width * 0.38));
    const short = name => PS.fitText(name, 11, maxNameW - 12);
    const nameW = Math.min(maxNameW, 12 + Math.max(...people.map(s => PS.textWidth(short(PS.personName(s.person)), 11))));
    const innerW = width - nameW - 8;
    const x = d3.scaleBand(keys, [0, innerW]);
    const markW = x.step() >= 4 ? x.step() - 1 : x.step();
    const rowH = 14, markH = 10;
    const headH = 24 + 14 * PS.sourceMarkers(PS.selectedKinds()).length;

    // Header: period labels and data-source marker labels; it stays put
    // while the rows scroll.
    const header = d3.create("svg").attr("viewBox", `0 0 ${width} ${headH}`).attr("height", headH)
      .attr("aria-hidden", "true");
    const every = Math.max(1, Math.ceil(56 / x.step()));
    const hg = header.append("g").attr("transform", `translate(${nameW},0)`);
    keys.forEach((k, i) => {
      if (i % every || x(k) + PS.textWidth(scheme.short(k), 11) > innerW + 8) return;
      hg.append("text").attr("x", x(k)).attr("y", headH - 6).text(scheme.short(k));
    });
    const markers = PS.sourceMarkers(PS.selectedKinds())
      .map(m => ({...m, key: scheme.key(m.day)}))
      .filter(m => m.key > minKey && m.key <= maxKey);
    PS.markerLabels(hg, markers, x, 10, -nameW, innerW + 8);

    // Body: one row per person.
    const height = people.length * rowH;
    const body = d3.create("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("height", height)
      .attr("role", "group")
      .attr("aria-label", "Timeline per person. Arrow keys move between people; the Table button lists them.");
    // Every other row shaded, and light gridlines at the labeled periods, so
    // a row is easy to follow across.
    people.forEach((_, row) => {
      if (row % 2) body.append("rect").attr("x", 0).attr("y", row * rowH).attr("width", width)
        .attr("height", rowH).attr("fill", "var(--wash)");
    });
    const bg = body.append("g").attr("transform", `translate(${nameW},0)`);
    bg.append("g").attr("class", "grid").selectAll("line")
      .data(keys.filter((k, i) => i % every === 0)).join("line")
      .attr("x1", k => x(k)).attr("x2", k => x(k)).attr("y1", 0).attr("y2", height);
    const markerG = bg.append("g").attr("class", "marker");
    for (const m of markers) {
      markerG.append("line").attr("x1", x(m.key)).attr("x2", x(m.key)).attr("y1", 0).attr("y2", height);
    }
    const hits = [];
    people.forEach((s, row) => {
      const y = row * rowH;
      const name = PS.personName(s.person);
      body.append("text").attr("class", s.current ? "name current" : "name")
        .attr("x", 0).attr("y", y + rowH / 2).attr("dominant-baseline", "middle").text(short(name));
      const active = perPerson.get(s.person);
      for (const [key, n] of active) {
        bg.append("rect").attr("x", x(key)).attr("y", y + (rowH - markH) / 2)
          .attr("width", Math.max(1, markW)).attr("height", markH).attr("rx", Math.min(2, markW / 2))
          .attr("fill", `var(--ord-${binOf(n) + 1})`);
      }
      const summary = [
        {name: "segment", value: s.segment},
        {name: "first", value: dayText(s.first)},
        {name: "last", value: dayText(s.last)},
        {name: "activity", value: s.activity},
        {name: "active quarters", value: s.quarters},
        {name: "returns", value: s.returns},
      ];
      const login = data.people.login[s.person];
      const title = `${name}${login && login !== name ? ` (${login})` : ""}${s.current ? " · active now" : ""}`;
      const show = event => {
        const lines = [...summary];
        if (event instanceof Event && "clientX" in event) {
          const [px] = d3.pointer(event, bg.node());
          const key = keys[Math.floor(px / x.step())];
          if (key !== undefined) lines.unshift({name: `in ${scheme.label(key)}`, value: active.get(key) || 0});
        }
        PS.showTooltip(event, title, lines);
      };
      hits.push(body.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", width).attr("height", rowH)
        .attr("role", "img")
        .attr("aria-label", `${name}: ${s.segment}, ${dayText(s.first)} to ${dayText(s.last)}, ` +
          `${s.activity} activity in ${s.quarters} quarters${s.current ? ", active now" : ""}`)
        .on("pointermove", show)
        .on("focus", event => show(event.currentTarget))
        .on("pointerleave blur", PS.hideTooltip).node());
    });
    PS.rovingFocus(hits, 0, "ArrowUp", "ArrowDown");

    const scroll = PS.el("div", {class: "scroll"});
    scroll.addEventListener("scroll", PS.hideTooltip, {passive: true});
    scroll.append(body.node());
    figure.plot.replaceChildren(header.node(), scroll);
  },
});
