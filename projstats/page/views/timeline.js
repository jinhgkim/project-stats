// View: one row per person, ordered by first activity, with a mark for each
// period they were active in. One segment at a time is listed.

const NAME_SIZE = 13;  // px; keep in step with `.plot .name` in template.html

PS.registerView({
  id: "timeline",
  title: "Timeline per person",
  tab: "people",
  order: 40,
  render(figure, {data, rows, rowsExcept, state, set}) {
    const gap = data.settings.return_gap_days;
    const rules = PS.segmentRules(state);
    const scheme = PS.periodScheme(state.period);
    const {stats} = PS.metrics.personStats(rows, data, rules, gap, rowsExcept("people"));
    const ids = PS.metrics.SEGMENTS;
    // One segment, core by default. Older links may list several: the first counts.
    const picked = (state.tl || "").split(",").find(s => ids.includes(s)) || "core";
    const counts = Object.fromEntries(ids.map(id => [id, stats.filter(s => s.segment === id).length]));

    // One choice of segment, built once and kept in step with the state. Arrow
    // keys move and select, like a radio group.
    const names = {core: "Core", regular: "Regular", casual: "Casual", "one-time": "One-time"};
    if (!figure.toggles) {
      figure.toggles = ids.map(id => {
        const button = PS.el("button", {type: "button", role: "radio"});
        const choose = () => { if (figure.picked !== id) set({tl: id === "core" ? undefined : id}); };
        button.onclick = choose;
        button.onfocus = choose;
        return button;
      });
      PS.rovingFocus(figure.toggles, 0, "ArrowLeft", "ArrowRight");
      figure.controls.append(PS.el("span", {class: "label", id: "timeline-show"}, "Show"),
        PS.el("span", {class: "choice", role: "radiogroup", "aria-labelledby": "timeline-show"}, ...figure.toggles));
    }
    figure.picked = picked;
    figure.toggles.forEach((button, i) => {
      const label = `${names[ids[i]]} ${counts[ids[i]]}`;
      button.textContent = label;
      button.setAttribute("data-label", label);
      button.setAttribute("aria-checked", String(ids[i] === picked));
      button.setAttribute("tabindex", ids[i] === picked ? 0 : -1);
    });

    const people = stats.filter(s => s.segment === picked)
      .sort((a, b) => a.first - b.first || PS.personName(a.person).localeCompare(PS.personName(b.person)));

    figure.subtitle.textContent = "When was each person active, and who is still around?";
    PS.fillHowto(figure, [
      `Bold names: active in the last ${gap} days of data.`,
    ]);
    const BINS = [2, 6, 21];
    const binOf = n => BINS.filter(t => n >= t).length;
    PS.fillLegend(figure, ["1 activity", "2–5", "6–20", "21+"]
      .map((name, i) => ({name, color: `var(--ord-${i + 1})`, shape: "rect"})));
    const dayText = d => PS.dayToText(d);
    PS.fillTable(figure, [
      {name: "Person", value: s => PS.personButton(s.person, state, "people-")},
      {name: "Segment", value: s => s.segment},
      {name: "First", value: s => dayText(s.first)},
      {name: "Last", value: s => dayText(s.last)},
      {name: "Activity", value: s => s.activity},
      {name: "Active quarters", value: s => s.quarters},
      {name: "Returns", value: s => s.returns},
      {name: "Active now", value: s => (s.current ? "yes" : "no")},
    ], people);

    if (!people.length) {
      PS.charts.empty(figure, stats.length ? "No one in the chosen segments." : "No activity matches the filters.");
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

    const width = PS.charts.width(figure);
    const maxNameW = Math.min(220, Math.round(width * 0.38));
    const short = name => PS.fitText(name, NAME_SIZE, maxNameW - 12);
    const nameW = Math.min(maxNameW, 12 + Math.max(...people.map(s => PS.textWidth(short(PS.personName(s.person)), NAME_SIZE))));
    const innerW = width - nameW - 8;
    const x = d3.scaleBand(keys, [0, innerW]);
    const markW = x.step() >= 4 ? x.step() - 1 : x.step();
    const rowH = 22, markH = 14;
    const headH = 24 + 14 * PS.sourceMarkers(PS.selectedKinds()).length;

    // Header: period labels and data-source marker labels; it stays put
    // while the rows scroll.
    const header = PS.charts.svg(width, headH, null);
    const every = PS.charts.labelEvery(x.step());
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
    const body = PS.charts.svg(width, height,
      "Timeline per person. Arrow keys move between people; the Table button lists them.");
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
    const targets = [];
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
      targets.push({
        node: body.append("rect").attr("class", "hit")
          .attr("x", 0).attr("y", y).attr("width", width).attr("height", rowH),
        label: `${name}: ${s.segment}, ${dayText(s.first)} to ${dayText(s.last)}, ` +
          `${s.activity} activity in ${s.quarters} quarters${s.current ? ", active now" : ""}`,
        show,
      });
    });
    PS.charts.hits(figure, targets.map(t => t.node), {
      keys: ["ArrowUp", "ArrowDown"],
      current: 0,
      label: i => targets[i].label,
      show: (i, anchor) => targets[i].show(anchor),
    });

    PS.charts.scrollArea(figure, {header, body});
  },
});
