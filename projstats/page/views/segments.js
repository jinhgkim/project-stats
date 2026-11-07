// View: people per segment (core, regular, casual, one-time), with how many
// are active now, beside each segment's share of all activity.

PS.registerView({
  id: "segments",
  title: "Segments",
  tab: "people",
  width: "half",
  order: 20,
  render(figure, {data, rows, state}) {
    const gap = data.settings.return_gap_days;
    const rules = PS.segmentRules(state);
    const {stats} = PS.metrics.personStats(rows, data, rules, gap);
    const ranged = Boolean(state.from || state.to);
    const names = {
      core: `Core (${rules.core}+ quarters)`,
      regular: `Regular (${rules.regular}–${rules.core - 1} quarters)`,
      casual: `Casual (under ${rules.regular} quarters)`,
      "one-time": "One-time (1 activity)",
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

    figure.subtitle.textContent = "How is the work spread between long-time regulars and occasional contributors?";
    PS.fillHowto(figure, [
      `A person's segment depends on how many calendar quarters they were active in` +
        `${ranged ? " within the selected dates" : ""}; the thresholds above set the cutoffs.`,
      "One-time: exactly one activity. Casual: more than one, in fewer quarters than regular.",
      `Active now (solid part of each bar): any activity in the last ${gap} days of the data shown.`,
      "Right: each segment's share of all activity, so a small group can do most of the work.",
    ]);
    PS.fillLegend(figure, [
      {name: "Active now", color: "var(--series-1)", shape: "rect"},
      {name: "Not active now", color: "var(--series-1-faint)", shape: "rect"},
    ]);
    const pct = v => `${(v * 100).toFixed(1)}%`;
    PS.fillTable(figure, [
      {name: "Segment", value: s => s.name},
      {name: "People", value: s => s.people},
      {name: "Active now", value: s => s.current},
      {name: "Activity", value: s => s.activity},
      {name: "Share of activity", value: s => pct(s.share)},
    ], segments);

    if (!stats.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No activity matches the filters."));
      return;
    }

    const width = Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
    // Narrow screens put each segment's name on its own line above the bars.
    const stacked = width < 560;
    const labelW = stacked ? 0 : Math.min(200, 8 + Math.max(...segments.map(s => PS.textWidth(s.name, 12))));
    const rowH = stacked ? 42 : 28, barH = 16, top = 22;
    const barTop = stacked ? 20 : (rowH - barH) / 2;
    const height = top + segments.length * rowH;
    const gapX = 24;
    const panelW = (width - labelW - gapX) / 2;
    const peopleText = s => `${s.people} · ${s.current} now`;
    const shareText = s => pct(s.share);
    // Each panel leaves room for its value labels after the longest bar.
    const peopleRoom = 8 + Math.max(...segments.map(s => PS.textWidth(peopleText(s), 12)));
    const shareRoom = 8 + PS.textWidth("100.0%", 12);
    const xPeople = d3.scaleLinear([0, d3.max(segments, s => s.people) || 1], [0, Math.max(20, panelW - peopleRoom)]);
    const xShare = d3.scaleLinear([0, 1], [0, Math.max(20, panelW - shareRoom)]);
    const shareX0 = labelW + panelW + gapX;

    const svg = d3.create("svg")
      .attr("viewBox", `0 0 ${width} ${height}`).attr("height", height)
      .attr("role", "group")
      .attr("aria-label", "Segments. Arrow keys move between segments; the Table button shows the numbers.");
    svg.append("text").attr("x", labelW).attr("y", 12).text("People");
    svg.append("text").attr("x", shareX0).attr("y", 12).text(stacked ? "Share of activity" : "Share of all activity");

    const roundRight = (x0, y0, w, h, r) => {
      r = Math.min(r, w, h / 2);
      return `M${x0},${y0}H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}` +
        `V${y0 + h - r}Q${x0 + w},${y0 + h} ${x0 + w - r},${y0 + h}H${x0}Z`;
    };
    const hits = [];
    segments.forEach((s, i) => {
      const y = top + i * rowH;
      const by = y + barTop;
      const valueY = by + barH / 2;
      const g = svg.append("g");
      g.append("text").attr("class", "label").attr("x", 0).attr("y", stacked ? y + 10 : valueY)
        .attr("dominant-baseline", "middle").text(s.name);

      // People: the active-now part first, then the rest, 2px apart.
      const wNow = xPeople(s.current);
      const wAll = xPeople(s.people);
      if (s.people > 0) {
        if (s.current > 0) {
          const now = s.current === s.people ? roundRight(labelW, by, wNow, barH, 4)
            : `M${labelW},${by}h${Math.max(0, wNow - 1)}v${barH}h${-Math.max(0, wNow - 1)}Z`;
          g.append("path").attr("d", now).attr("fill", "var(--series-1)");
        }
        if (s.current < s.people) {
          const x0 = labelW + (s.current > 0 ? wNow + 1 : 0);
          g.append("path").attr("d", roundRight(x0, by, Math.max(1, labelW + wAll - x0), barH, 4))
            .attr("fill", "var(--series-1-faint)");
        }
      }
      g.append("text").attr("class", "label").attr("x", labelW + wAll + 6).attr("y", valueY)
        .attr("dominant-baseline", "middle").text(peopleText(s));

      const wShare = xShare(s.share);
      if (wShare > 0) {
        g.append("path").attr("d", roundRight(shareX0, by, Math.max(1, wShare), barH, 4))
          .attr("fill", "var(--series-1)");
      }
      g.append("text").attr("class", "label").attr("x", shareX0 + wShare + 6).attr("y", valueY)
        .attr("dominant-baseline", "middle").text(shareText(s));

      const show = event => PS.showTooltip(event, s.name, [
        {name: "people", value: s.people},
        {name: "active now", value: s.current, color: "var(--series-1)"},
        {name: "activity", value: s.activity},
        {name: "share of activity", value: pct(s.share)},
      ]);
      hits.push(g.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", width).attr("height", rowH)
        .attr("role", "img")
        .attr("aria-label", `${s.name}: ${s.people} people, ${s.current} active now, ` +
          `${pct(s.share)} of activity`)
        .on("pointermove", show)
        .on("focus", event => show(event.currentTarget))
        .on("pointerleave blur", PS.hideTooltip).node());
    });
    PS.rovingFocus(hits, 0, "ArrowUp", "ArrowDown");
    figure.plot.replaceChildren(svg.node());
  },
});
