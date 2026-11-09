// View: one row per theme (share now vs earlier, documents, first and last
// seen, peak period, top contributors). A theme's name opens the list of its commits,
// PRs, and issues, with GitHub links.

PS.registerView({
  id: "theme-table",
  title: "Theme details",
  tab: "themes",
  feature: "themes",
  order: 60,
  noTable: true,
  render(figure, {data, rowsExcept, state, set}) {
    if (!data.themes.name.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No themes yet; run projstats tag."));
      figure.details.hidden = true;
      return;
    }
    const kind = PS.themePeriod(state);
    const scheme = PS.periodScheme(kind);
    const rows = rowsExcept("theme");
    const r = PS.metrics.themeTrends(rows, data, scheme, {skipInProgress: kind === "release"});
    const cols = r.periods.filter(p => p.covered && p.activity > 0);
    const name = t => data.themes.name[t];
    const pct = v => `${(v * 100).toFixed(1)}%`;
    const day = d => PS.dayToText(d);

    // Documents per theme, within the date range.
    const lo = state.from ? PS.dateToDay(state.from) : -Infinity;
    const hi = state.to ? PS.dateToDay(state.to) : Infinity;
    const docsOf = new Map();
    data.themes.doc.forEach((d, k) => {
      const t = data.themes.theme[k];
      if (data.docs.day[d] < lo || data.docs.day[d] > hi) return;
      if (!docsOf.has(t)) docsOf.set(t, []);
      docsOf.get(t).push(d);
    });

    const themes = r.present.filter(t => docsOf.has(t) || r.lastDay[t] !== null).map(t => {
      const docs = (docsOf.get(t) || []).sort((a, b) => data.docs.day[b] - data.docs.day[a] || b - a);
      let peak = null;
      for (const p of cols) {
        const s = p.themes.find(x => x.theme === t);
        if (s && s.share > 0 && (!peak || s.share > peak.share)) {
          peak = {label: p.partial && scheme.soFar ? `${p.label} so far` : p.label, share: s.share};
        }
      }
      return {
        t, docs, peak, trend: r.trends.get(t), contributors: r.contributors.get(t) || [],
        first: docs.length ? data.docs.day[docs[docs.length - 1]] : null, last: r.lastDay[t],
      };
    }).sort((a, b) => (b.trend ? b.trend.recentShare : 0) - (a.trend ? a.trend.recentShare : 0) ||
      b.docs.length - a.docs.length || name(a.t).localeCompare(name(b.t)));
    // Documents is the only sortable column; a third click restores the order above.
    if (figure.docSort) {
      const sign = figure.docSort === "asc" ? 1 : -1;
      themes.sort((a, b) => sign * (a.docs.length - b.docs.length) || name(a.t).localeCompare(name(b.t)));
    }

    figure.subtitle.textContent = "What's in each theme, and who works on it? Choose a theme to see the activity on it.";
    PS.fillHowto(figure, [
      `Documents: commits, PRs, and issues tagged with the theme${state.from || state.to ? " within the selected dates" : ""}.`,
      `Peak: the ${scheme.name} with the theme's largest share, and that share, as in Themes over time.`,
      "Top people: most activity on the theme's documents; the list below shows five.",
    ]);

    if (!themes.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No themed activity matches the filters."));
      figure.details.hidden = true;
      return;
    }

    const selected = PS.selectedThemes(state);
    if (figure.open === undefined) figure.open = selected.length ? selected[0] : null;
    const sortButton = PS.el("button", {
      type: "button", class: "sort",
      "aria-label": figure.docSort
        ? `Documents, ${figure.docSort === "asc" ? "fewest" : "most"} first. ` +
          `Click to ${figure.docSort === "asc" ? "restore the default order" : "reverse"}.`
        : "Sort by Documents",
    }, "Documents", PS.el("span", {
      class: figure.docSort ? (figure.docSort === "asc" ? "chev up" : "chev") : "sort-none", "aria-hidden": "true",
    }));
    sortButton.onclick = () => {
      figure.docSort = figure.docSort === undefined ? "desc" : figure.docSort === "desc" ? "asc" : undefined;
      this.render(figure, {data, rowsExcept, state, set});
    };
    const head = PS.el("tr", {}, ["Theme", "Documents", "First seen", "Last seen",
      "Peak", "Top people"].map(h => h === "Documents"
      ? PS.el("th", {scope: "col", "aria-sort": figure.docSort ? (figure.docSort === "asc" ? "ascending" : "descending") : "none"}, sortButton)
      : PS.el("th", {scope: "col"}, h)));
    const body = themes.map(x => {
      const button = PS.el("button", {
        type: "button", class: "link-button", "aria-expanded": String(figure.open === x.t),
      }, name(x.t));
      button.onclick = () => {
        figure.open = figure.open === x.t ? null : x.t;
        figure.showAll = false;
        this.render(figure, {data, rowsExcept, state, set});
        if (figure.open !== null) figure.details.scrollIntoView({block: "nearest"});
      };
      return PS.el("tr", {class: selected.includes(x.t) ? "selected" : null},
        PS.el("td", {}, button),
        PS.el("td", {}, x.docs.length),
        PS.el("td", {class: "nowrap"}, x.first === null ? "–" : day(x.first)),
        PS.el("td", {class: "nowrap"}, x.last === null ? "–" : day(x.last)),
        PS.el("td", {class: "nowrap"}, x.peak ? `${x.peak.label} · ${pct(x.peak.share)}` : "–"),
        PS.el("td", {class: "people"}, x.contributors.slice(0, 3)
          .map(c => `${PS.personName(c.person)} ${c.code + c.discussion}`).join(", ") || "–"));
    });
    figure.plot.replaceChildren(PS.el("div", {class: "table-wrap"},
      PS.el("table", {class: "data themes"}, PS.el("thead", {}, head), PS.el("tbody", {}, body))));

    const open = themes.find(x => x.t === figure.open);
    figure.details.hidden = !open;
    if (!open) return;
    const filtered = selected.includes(open.t);
    const filterButton = PS.el("button", {type: "button"},
      filtered ? (selected.length === 1 ? "Show all themes on the page" : "Remove this theme from the filter")
        : selected.length ? "Add this theme to the filter" : "Filter the page to this theme");
    filterButton.onclick = () => set(PS.themePatch(
      filtered ? selected.filter(t => t !== open.t) : [...selected, open.t]));
    // The theme's activity over the whole range, after the filters other than Theme.
    const {themesOf, tagged} = PS.metrics.themeIndex(data);
    const A = data.activity;
    const mine = rows.filter(i => {
      const d = A.doc[i];
      return d >= 0 && tagged[d] && (themesOf.get(d) || []).includes(open.t);
    });
    figure.details.replaceChildren(...PS.themeActivity(figure, {
      title: name(open.t),
      rows: mine,
      extra: [filterButton],
      onClose: () => {
        figure.open = null;
        this.render(figure, {data, rowsExcept, state, set});
      },
      rerender: () => this.render(figure, {data, rowsExcept, state, set}),
    }));
  },
});
