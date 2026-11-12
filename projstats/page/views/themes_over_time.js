// View: each theme's share of activity per period, as a heatmap. Only
// periods that are mostly tagged get columns. Hovering a theme shows its latest
// share and how it compares with earlier ones. A cell opens, in the pane below,
// the activity its share is made of, listed like the People tab's pane.

// The theme views' period is the Group by choice.
PS.themePeriod = state => state.period;

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
    const untagged = r.periods.filter(p => !p.covered && p.activity > 0).map(p => p.label);
    figure.controls.replaceChildren(...(untagged.length ? [PS.el("span", {class: "coverage"},
      `Left out because they aren't tagged yet: ${untagged.slice(0, 5).join(", ")}` +
      `${untagged.length > 5 ? ` and ${untagged.length - 5} more` : ""}.`)] : []));

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
      : `Hover a theme to compare its share in ${r.periods[r.recent].label} with ${r.earlier.length === 1 ? r.periods[r.earlier[0]].label
        : `all ${r.earlier.length} earlier ${scheme.name}s combined`}.`;
    figure.subtitle.textContent = "Which areas of work are getting more attention, and which less?";
    PS.fillHowto(figure, [
      `Each cell: activity on the theme's documents / all activity on tagged documents, in that ${scheme.name}, as a percent. A blank cell means no activity.`,
      "A PR's reviews, comments, and linked commits count toward its themes; a document with two themes counts for both.",
      `Documents in the tooltip: the PRs opened, issues opened, and commits not tied to a PR in that ${scheme.name} that are tagged with the theme.`,
      compared,
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

    // The latest column's share, for a row's label and its tooltip off the cells.
    const latest = t => cols.slice(-1).map(p => ({
      name: p.label + (p.partial && scheme.soFar ? " so far" : ""),
      value: shareOf(p, t) ? pct(shareOf(p, t).share) : "–",
    }));
    PS.charts.heatmap(figure, {
      rows: themes,
      cols,
      rowLabel: i => name(themes[i]),
      rowCurrent: i => selected.includes(themes[i]),
      colLabel: k => cols[k].short,
      colNote: k => (cols[k].partial && scheme.soFar ? "so far" : null),
      cell: (i, k) => {
        const p = cols[k];
        const s = p && shareOf(p, themes[i]);
        return s ? {text: shareNum(s.share), bin: binOf(s.share), faded: p.partial} : null;
      },
      label: `Themes over time by ${scheme.name}. Up and down arrows move between themes, left and right ` +
        `between ${scheme.name}s, and Enter lists the activity; the Table button shows the numbers.`,
      rowLabelAria: i => `${name(themes[i])}: ` +
        latest(themes[i]).map(a => `${a.name} ${a.value}`).join(", ") +
        `. Left and right arrows choose a ${scheme.name}; Enter lists its activity.`,
      tooltip: (i, k, anchor) => {
        const t = themes[i];
        const trend = r.trends.get(t);
        const p = cols[k];
        const s = p && shareOf(p, t);
        const all = latest(t);
        const lines = s ? [
          {name: `share in ${p.label}`, value: pct(s.share)},
          {name: "documents", value: s.docs},
          {name: "commits", value: s.commits},
          {name: "discussion", value: s.discussion},
          {name: "people", value: s.people},
        ] : all;
        PS.showTooltip(anchor, name(t), trend && lines === all
          ? [...lines, {name: `${r.periods[r.recent].label} vs earlier`, value: `${pct(trend.recentShare)} vs ${pct(trend.earlierShare)}`}]
          : lines);
      },
      onPick: (i, k) => {
        const t = themes[i];
        const p = cols[k];
        const same = picked && picked.t === t && picked.key === p.key;
        figure.pick = same ? null : {t, key: p.key};
        figure.showAll = false;
        this.render(figure, args);
        if (figure.pick) figure.details.scrollIntoView({behavior: "smooth", block: "nearest"});
      },
      picked: picked && {row: themes.indexOf(picked.t), col: pickedCol},
      focusRow: Math.max(0, themes.indexOf(selected[0])),
    });

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
