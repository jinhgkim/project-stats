// View: each theme's share of activity per release cycle, as a heatmap. Only
// periods that are mostly tagged get columns. Whether a theme is rising or
// fading shows on hover, not as row labels. A cell opens, in the pane below,
// the activity its share is made of, listed like the People tab's pane.

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
  render(figure, args) {
    const {data, rowsExcept, state} = args;
    figure.details.hidden = true;
    if (!data.themes.name.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No themes yet; run projstats tag."));
      return;
    }
    const kind = PS.themePeriod(state);
    const scheme = PS.periodScheme(kind);
    // Every theme is shown even when the theme filter picks some; those are marked.
    const rows = rowsExcept("theme");
    const r = PS.metrics.themeTrends(rows, data, scheme, {skipInProgress: kind === "release"});
    const selected = PS.selectedThemes(state);
    const cols = r.periods.filter(p => p.covered && p.activity > 0);
    const untagged = r.periods.filter(p => !p.covered && p.activity > 0).length;
    const scrolled = figure.plot.querySelector(".scroll");
    const scrollTop = scrolled ? scrolled.scrollTop : 0;

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
      `Each cell: the theme's share, in percent, of all activity on tagged documents in that ${scheme.name}. A blank cell means no activity.`,
      "A PR's reviews, comments, and linked commits count toward its themes; a document with two themes counts for both.",
      `Choose a cell to list the activity behind it: commits, PRs, reviews, and comments on the theme's documents in that ${scheme.name}. With the keyboard, use the up and down arrows to pick a theme, the left and right arrows to pick a ${scheme.name}, and Enter to list.`,
      compared,
      untagged ? `${untagged} earlier ${scheme.name}${untagged === 1 ? " isn't" : "s aren't"} tagged yet, so ` +
        `${untagged === 1 ? "it's" : "they're"} left out.` : null,
    ].filter(Boolean));

    const BINS = [0.01, 0.03, 0.06, 0.10, 0.15];
    const binOf = v => BINS.filter(t => v >= t).length;
    PS.fillLegend(figure, ["under 1%", "1–3%", "3–6%", "6–10%", "10–15%", "15%+"]
      .map((n, i) => ({name: n, color: `var(--seq-${i + 1})`, shape: "rect"})));
    const unit = "Share of activity, in %";
    figure.legend.append(PS.el("span", {class: "unit"}, unit));
    const shareNum = v => (v * 100).toFixed(1);
    const pct = v => (v === null || v === undefined ? "–" : `${shareNum(v)}%`);
    PS.fillTable(figure, [
      {name: "Theme", value: t => name(t)},
      ...cols.map(p => ({
        name: p.label + (p.partial && scheme.soFar ? " (so far)" : ""),
        value: t => (shareOf(p, t) ? shareNum(shareOf(p, t).share) : "–"),
      })),
    ], themes, unit);

    if (!cols.length) {
      const days = data.themes.tagged.map(d => data.docs.day[d]);
      figure.plot.replaceChildren(PS.el("p", {class: "empty"},
        `No tagged ${scheme.name}s match the filters.` +
        (days.length ? ` Theme tags cover documents from ${PS.dayToText(Math.min(...days))}.` : "")));
      return;
    }

    // The chosen cell is kept as a theme and a period key, so it survives
    // other filters; it is dropped when the filters remove the cell.
    const pickedCol = figure.pick ? cols.findIndex(p => p.key === figure.pick.key) : -1;
    const picked = pickedCol >= 0 && themes.includes(figure.pick.t) && shareOf(cols[pickedCol], figure.pick.t)
      ? figure.pick : null;
    if (!picked) figure.pick = null;
    // The column the arrow keys are on.
    if (figure.col === undefined || figure.col >= cols.length) figure.col = cols.length - 1;

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
      .attr("aria-label", `Themes over time by ${scheme.name}. Up and down arrows move between themes, left and right ` +
        `between ${scheme.name}s, and Enter lists the activity; the Table button shows the numbers.`);

    const colAt = event => Math.floor((d3.pointer(event, svg.node())[0] - x0) / cellW);
    const choose = (t, k, keyboard) => {
      const p = cols[k];
      if (!p || !shareOf(p, t)) return;
      PS.hideTooltip();
      figure.col = k;
      const same = picked && picked.t === t && picked.key === p.key;
      figure.pick = same ? null : {t, key: p.key};
      figure.showAll = false;
      figure.refocus = keyboard ? themes.indexOf(t) : undefined;
      this.render(figure, args);
      if (figure.pick) figure.details.scrollIntoView({behavior: "smooth", block: "nearest"});
    };

    const hits = [];
    themes.forEach((t, row) => {
      const y = row * rowH;
      const mid = y + rowH / 2;
      const g = svg.append("g");
      const trend = r.trends.get(t);
      g.append("text").attr("class", selected.includes(t) ? "label current" : "label")
        .attr("x", 0).attr("y", mid).attr("dominant-baseline", "middle").text(label(t));
      cols.forEach((p, i) => {
        const s = shareOf(p, t);
        const x = x0 + i * cellW;
        if (!s) return;
        const bin = binOf(s.share);
        g.append("rect").attr("x", x + 1).attr("y", y + 1).attr("width", cellW - 2).attr("height", rowH - 2)
          .attr("rx", 3).attr("fill", `var(--seq-${bin + 1})`).attr("opacity", p.partial ? 0.6 : 1);
        g.append("text").attr("class", bin >= 3 ? "cell-ink-inverse" : "cell-ink")
          .attr("x", x + cellW / 2).attr("y", mid).attr("text-anchor", "middle")
          .attr("dominant-baseline", "middle").text(shareNum(s.share));
      });

      const all = cols.map(p => ({name: p.label + (p.partial && scheme.soFar ? " so far" : ""), value: shareOf(p, t) ? pct(shareOf(p, t).share) : "–"}));
      // k: the column to describe; from the pointer when left out.
      const show = (event, k) => {
        if (k === undefined && event instanceof Event && "clientX" in event) {
          k = colAt(event);
          event.currentTarget.style.cursor = cols[k] && shareOf(cols[k], t) ? "pointer" : "";
        }
        const p = cols[k];
        const s = p && shareOf(p, t);
        let lines = all;
        if (s) {
          lines = [
            {name: `share in ${p.label}`, value: pct(s.share)},
            {name: "documents", value: s.docs},
            {name: "code (commits)", value: s.code},
            {name: "discussion", value: s.discussion},
            {name: "people", value: s.people},
          ];
        }
        const head = trend ? `${name(t)} · ${trend.label}` : name(t);
        PS.showTooltip(event, head, trend && lines === all
          ? [...lines, {name: "recent vs earlier", value: `${pct(trend.recentShare)} vs ${pct(trend.earlierShare)}`}]
          : lines);
      };
      hits.push(g.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", x0 + cols.length * cellW).attr("height", rowH)
        .attr("role", "button")
        .attr("aria-label", `${name(t)}${trend ? `, ${trend.label}` : ""}: ` +
          all.map(a => `${a.name} ${a.value}`).join(", ") +
          `. Left and right arrows choose a ${scheme.name}; Enter lists its activity.`)
        .on("pointermove", show)
        .on("click", event => choose(t, colAt(event), false))
        .on("keydown", event => {
          const step = {ArrowLeft: -1, ArrowRight: 1}[event.key];
          if (step !== undefined) {
            event.preventDefault();
            figure.col = Math.max(0, Math.min(cols.length - 1, figure.col + step));
            place(row);
            show(event.currentTarget, figure.col);
          } else if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            choose(t, figure.col, true);
          }
        })
        .on("focus", event => { place(row); show(event.currentTarget, figure.col); })
        .on("pointerleave blur", PS.hideTooltip)
        .on("blur.cursor", () => cursor.attr("display", "none")).node());
    });

    // Marks above the rows: the chosen cell, and the cell the arrow keys are on.
    const outline = (cls, k, row, stroke, w) => svg.append("rect").attr("class", cls)
      .attr("x", x0 + k * cellW + 1).attr("y", row * rowH + 1).attr("width", cellW - 2).attr("height", rowH - 2)
      .attr("rx", 3).attr("fill", "none").attr("stroke", stroke).attr("stroke-width", w)
      .attr("pointer-events", "none");
    if (picked) outline("picked", pickedCol, themes.indexOf(picked.t), "var(--text-primary)", 1.5);
    const cursor = outline("cursor", 0, 0, "var(--series-1)", 2).attr("display", "none");
    const place = row => cursor.attr("display", null)
      .attr("x", x0 + figure.col * cellW + 1).attr("y", row * rowH + 1);

    const current = figure.refocus !== undefined ? figure.refocus : Math.max(0, themes.indexOf(selected[0]));
    PS.rovingFocus(hits, current, "ArrowUp", "ArrowDown");
    const scroll = PS.el("div", {class: "scroll"});
    scroll.addEventListener("scroll", PS.hideTooltip, {passive: true});
    scroll.append(svg.node());
    figure.plot.replaceChildren(header.node(), scroll);
    scroll.scrollTop = scrollTop;
    if (figure.refocus !== undefined) {
      hits[figure.refocus].focus();
      figure.refocus = undefined;
    }

    if (!picked) return;
    const cell = cols[pickedCol];
    const period = cell.label + (cell.partial && scheme.soFar ? " so far" : "") + (kind === "release" && !/\bdev\b/.test(cell.label) ? " release" : "");
    // The activity the cell's share is made of: on documents tagged with the
    // theme, in this period, after the other filters.
    const index = r.periods.indexOf(cell);
    const {themesOf, tagged} = PS.metrics.themeIndex(data);
    const A = data.activity;
    const mine = rows.filter(i => {
      const d = A.doc[i];
      return d >= 0 && tagged[d] && r.periodOf(A.day[i]) === index && (themesOf.get(d) || []).includes(picked.t);
    });
    figure.details.hidden = false;
    figure.details.replaceChildren(...PS.themeActivity(figure, {
      title: `${name(picked.t)} · ${period}`,
      rows: mine,
      onClose: () => {
        figure.pick = null;
        this.render(figure, args);
      },
      rerender: () => this.render(figure, args),
    }));
  },
});
