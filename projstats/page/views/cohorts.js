// View: cohorts by the year of each person's first activity, and the share
// of each cohort active again 1, 2, and 5 years later, as a heatmap.

PS.registerView({
  id: "cohorts",
  title: "Cohorts by first year",
  order: 30,
  render(figure, {data, rows, state}) {
    const gap = data.settings.return_gap_days;
    const {stats, dataEnd} = PS.metrics.personStats(rows, data, PS.segmentRules(state), gap);
    const cohorts = stats.length ? PS.metrics.cohorts(stats, dataEnd) : [];
    const offsets = PS.metrics.COHORT_OFFSETS;
    const ranged = Boolean(state.from || state.to);

    // Six shade steps; the top three take the inverse ink for contrast.
    const BINS = [0.05, 0.10, 0.20, 0.30, 0.50];
    const binOf = v => BINS.filter(t => v >= t).length;
    const binNames = ["under 5%", "5–10%", "10–20%", "20–30%", "30–50%", "50%+"];

    figure.subtitle.textContent =
      `People grouped by the calendar year of their first activity of the selected kinds` +
      `${ranged ? " within the selected dates" : ""}. Each cell: the share of that group active ` +
      `again 1, 2, or 5 years later; n/a until that year is complete. One-time: a single activity.`;
    PS.fillLegend(figure, binNames.map((name, i) => ({name, color: `var(--seq-${i + 1})`, shape: "rect"})));
    const pct = (n, of) => (of ? `${Math.round((100 * n) / of)}%` : "–");
    PS.fillTable(figure, [
      {name: "First year", value: c => c.year},
      {name: "People", value: c => c.size},
      {name: "One-time", value: c => `${c.oneTime} (${pct(c.oneTime, c.size)})`},
      ...offsets.map(n => ({
        name: `Year +${n}`,
        value: c => (c.after[n] === null ? "n/a" : `${c.after[n]} (${pct(c.after[n], c.size)})`),
      })),
    ], cohorts);

    if (!cohorts.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No activity matches the filters."));
      return;
    }

    const width = Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
    const rowH = 24, top = 22;
    const height = top + cohorts.length * rowH;
    const colYear = 48, colSize = 56, colOne = 72;
    const cellsX = colYear + colSize + colOne;
    const cellW = Math.min(120, (width - cellsX) / offsets.length);

    const svg = d3.create("svg")
      .attr("viewBox", `0 0 ${width} ${height}`).attr("height", height)
      .attr("role", "group")
      .attr("aria-label", "Cohorts by first year. Arrow keys move between years; the Table button shows the numbers.");
    const head = [["First year", 0, "start"], ["People", colYear + colSize - 8, "end"],
      ["One-time", cellsX - 8, "end"],
      ...offsets.map((n, i) => [`Year +${n}`, cellsX + i * cellW + cellW / 2, "middle"])];
    for (const [text, x, anchor] of head) {
      svg.append("text").attr("x", x).attr("y", 12).attr("text-anchor", anchor).text(text);
    }

    const hits = [];
    cohorts.forEach((c, i) => {
      const y = top + i * rowH;
      const mid = y + rowH / 2;
      const g = svg.append("g");
      const text = (x, anchor, value, cls = "label") => g.append("text").attr("class", cls)
        .attr("x", x).attr("y", mid).attr("text-anchor", anchor)
        .attr("dominant-baseline", "middle").text(value);
      text(0, "start", c.year);
      text(colYear + colSize - 8, "end", c.size);
      text(cellsX - 8, "end", pct(c.oneTime, c.size));
      offsets.forEach((n, k) => {
        const x = cellsX + k * cellW;
        const v = c.after[n];
        if (v === null) {
          text(x + cellW / 2, "middle", "n/a");
          return;
        }
        const bin = binOf(c.size ? v / c.size : 0);
        g.append("rect").attr("x", x + 1).attr("y", y + 1).attr("width", cellW - 2).attr("height", rowH - 2)
          .attr("rx", 3).attr("fill", `var(--seq-${bin + 1})`);
        text(x + cellW / 2, "middle", pct(v, c.size), bin >= 3 ? "cell-ink-inverse" : "cell-ink");
      });

      const show = event => PS.showTooltip(event, `First active in ${c.year}`, [
        {name: "people", value: c.size},
        {name: "one-time", value: `${c.oneTime} (${pct(c.oneTime, c.size)})`},
        ...offsets.map(n => ({
          name: `active in ${c.year + n}`,
          value: c.after[n] === null ? "n/a" : `${c.after[n]} (${pct(c.after[n], c.size)})`,
        })),
      ]);
      hits.push(g.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", cellsX + offsets.length * cellW).attr("height", rowH)
        .attr("role", "img")
        .attr("aria-label", `First active in ${c.year}: ${c.size} people, ${pct(c.oneTime, c.size)} one-time, ` +
          offsets.map(n => `year +${n} ${c.after[n] === null ? "n/a" : pct(c.after[n], c.size)}`).join(", "))
        .on("pointermove", show)
        .on("focus", event => show(event.currentTarget))
        .on("pointerleave blur", PS.hideTooltip).node());
    });
    PS.rovingFocus(hits, hits.length - 1, "ArrowUp", "ArrowDown");
    figure.plot.replaceChildren(svg.node());
  },
});
