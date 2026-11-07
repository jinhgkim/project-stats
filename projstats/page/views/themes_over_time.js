// View: each theme's share of activity per release cycle, as a heatmap. Only
// periods that are mostly tagged get columns. Whether a theme is rising or
// fading shows on hover, not as row labels.

// The theme views' period: release cycles, or years when a project has no
// releases. Theme counts per month or quarter are too small to compare, so
// these views don't follow Group by.
PS.themePeriod = () => (PS.data.releases.day.length ? "release" : "year");

PS.registerView({
  id: "themes-over-time",
  title: "Themes over time",
  tab: "themes",
  feature: "themes",
  order: 50,
  render(figure, {data, rowsExcept, state}) {
    if (!data.themes.name.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No themes yet; run projstats tag."));
      return;
    }
    const kind = PS.themePeriod(state);
    const scheme = PS.periodScheme(kind);
    // Every theme is shown even when the theme filter picks one; that one is marked.
    const rows = rowsExcept("theme");
    const r = PS.metrics.themeTrends(rows, data, scheme, {skipInProgress: kind === "release"});
    const selected = PS.selectedTheme(state);
    const cols = r.periods.filter(p => p.covered && p.activity > 0);
    const untagged = r.periods.filter(p => !p.covered && p.activity > 0).length;

    const name = t => data.themes.name[t];
    const shareOf = (p, t) => {
      const s = p.themes.find(x => x.theme === t);
      return s ? s : null;
    };
    // Largest share first, in the period trends are measured on (the latest
    // complete one), or else the latest period shown.
    const ranked = r.recent !== null ? r.periods[r.recent] : cols[cols.length - 1];
    const rankShare = t => (ranked && shareOf(ranked, t) ? shareOf(ranked, t).share || 0 : 0);
    const themes = r.present.filter(t => cols.some(p => shareOf(p, t)))
      .sort((a, b) => rankShare(b) - rankShare(a) || name(a).localeCompare(name(b)));

    const compared = r.recent === null || !r.earlier.length ? null
      : `Hover a theme for its trend: ${r.periods[r.recent].label} vs ${r.earlier.length === 1 ? r.periods[r.earlier[0]].label
        : `${r.earlier.length} earlier ${scheme.name}s`}. Rising: 1.5× the share or more. Fading: 0.67× or less. ` +
        "Under 5 documents: too few to tell.";
    figure.subtitle.textContent = "Which areas of work are getting more attention, and which less?";
    PS.fillHowto(figure, [
      `Each cell: the theme's share of all activity on tagged documents in that ${scheme.name}.`,
      "A PR's reviews, comments, and linked commits count toward its themes; a document with two themes counts for both.",
      compared,
      "Use the Activity filter to compare Code with Discussion.",
      untagged ? `${untagged} earlier ${scheme.name}${untagged === 1 ? " isn't" : "s aren't"} tagged yet, so ` +
        `${untagged === 1 ? "it's" : "they're"} left out.` : null,
    ].filter(Boolean));

    const BINS = [0.01, 0.03, 0.06, 0.10, 0.15];
    const binOf = v => BINS.filter(t => v >= t).length;
    PS.fillLegend(figure, ["under 1%", "1–3%", "3–6%", "6–10%", "10–15%", "15%+"]
      .map((n, i) => ({name: n, color: `var(--seq-${i + 1})`, shape: "rect"})));
    const pct = v => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(1)}%`);
    PS.fillTable(figure, [
      {name: "Theme", value: t => name(t)},
      ...cols.map(p => ({
        name: p.label + (p.partial && scheme.soFar ? " (so far)" : ""),
        value: t => (shareOf(p, t) ? pct(shareOf(p, t).share) : "–"),
      })),
    ], themes);

    if (!cols.length) {
      const days = data.themes.tagged.map(d => data.docs.day[d]);
      figure.plot.replaceChildren(PS.el("p", {class: "empty"},
        `No tagged ${scheme.name}s match the filters.` +
        (days.length ? ` Theme tags cover documents from ${PS.dayToText(Math.min(...days))}.` : "")));
      return;
    }

    const width = Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
    const maxNameW = Math.min(220, Math.round(width * 0.4));
    const label = t => PS.fitText(name(t), 12, maxNameW);
    const nameW = 8 + Math.max(...themes.map(t => PS.textWidth(label(t), 12)));
    const x0 = nameW;
    const cellW = Math.min(110, (width - x0) / cols.length);
    const rowH = 24, top = 34;
    const height = themes.length * rowH;

    // The column labels stay put while the rows scroll.
    const header = d3.create("svg").attr("viewBox", `0 0 ${width} ${top}`).attr("height", top)
      .attr("aria-hidden", "true");
    cols.forEach((p, i) => {
      const cx = x0 + i * cellW + cellW / 2;
      header.append("text").attr("x", cx).attr("y", 14).attr("text-anchor", "middle").text(p.short);
      if (p.partial && scheme.soFar) header.append("text").attr("x", cx).attr("y", 27).attr("text-anchor", "middle").text("so far");
    });
    const svg = d3.create("svg")
      .attr("viewBox", `0 0 ${width} ${height}`).attr("height", height)
      .attr("role", "group")
      .attr("aria-label", `Themes over time by ${scheme.name}. Arrow keys move between themes; the Table button shows the numbers.`);

    const hits = [];
    themes.forEach((t, row) => {
      const y = row * rowH;
      const mid = y + rowH / 2;
      const g = svg.append("g");
      const trend = r.trends.get(t);
      g.append("text").attr("class", t === selected ? "label current" : "label")
        .attr("x", 0).attr("y", mid).attr("dominant-baseline", "middle").text(label(t));
      cols.forEach((p, i) => {
        const s = shareOf(p, t);
        const x = x0 + i * cellW;
        if (!s) {
          g.append("text").attr("x", x + cellW / 2).attr("y", mid).attr("text-anchor", "middle")
            .attr("dominant-baseline", "middle").text("–");
          return;
        }
        const bin = binOf(s.share);
        g.append("rect").attr("x", x + 1).attr("y", y + 1).attr("width", cellW - 2).attr("height", rowH - 2)
          .attr("rx", 3).attr("fill", `var(--seq-${bin + 1})`).attr("opacity", p.partial ? 0.6 : 1);
        g.append("text").attr("class", bin >= 3 ? "cell-ink-inverse" : "cell-ink")
          .attr("x", x + cellW / 2).attr("y", mid).attr("text-anchor", "middle")
          .attr("dominant-baseline", "middle").text(pct(s.share));
      });

      const all = cols.map(p => ({name: p.label + (p.partial && scheme.soFar ? " so far" : ""), value: shareOf(p, t) ? pct(shareOf(p, t).share) : "–"}));
      const show = event => {
        let lines = all;
        if (event instanceof Event && "clientX" in event) {
          const [px] = d3.pointer(event, svg.node());
          const p = cols[Math.floor((px - x0) / cellW)];
          const s = p && shareOf(p, t);
          if (s) {
            lines = [
              {name: `share in ${p.label}`, value: pct(s.share)},
              {name: "documents", value: s.docs},
              {name: "code (commits)", value: s.code},
              {name: "discussion", value: s.discussion},
              {name: "people", value: s.people},
            ];
          }
        }
        const head = trend ? `${name(t)} · ${trend.label}` : name(t);
        PS.showTooltip(event, head, trend && lines === all
          ? [...lines, {name: "recent vs earlier", value: `${pct(trend.recentShare)} vs ${pct(trend.earlierShare)}`}]
          : lines);
      };
      hits.push(g.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", x0 + cols.length * cellW).attr("height", rowH)
        .attr("role", "img")
        .attr("aria-label", `${name(t)}${trend ? `, ${trend.label}` : ""}: ` +
          all.map(a => `${a.name} ${a.value}`).join(", "))
        .on("pointermove", show)
        .on("focus", event => show(event.currentTarget))
        .on("pointerleave blur", PS.hideTooltip).node());
    });
    PS.rovingFocus(hits, Math.max(0, themes.indexOf(selected)), "ArrowUp", "ArrowDown");
    const scroll = PS.el("div", {class: "scroll"});
    scroll.addEventListener("scroll", PS.hideTooltip, {passive: true});
    scroll.append(svg.node());
    figure.plot.replaceChildren(header.node(), scroll);
  },
});
