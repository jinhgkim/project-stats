// View: one row per theme (documents, first and last seen, peak period,
// trend, top contributors). A theme's name opens the list of its commits,
// PRs, and issues, with GitHub links.

PS.registerView({
  id: "theme-table",
  title: "Theme details",
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
          peak = {label: p.partial ? `${p.label} so far` : p.label, share: s.share};
        }
      }
      return {
        t, docs, peak, trend: r.trends.get(t), contributors: r.contributors.get(t) || [],
        first: docs.length ? data.docs.day[docs[docs.length - 1]] : null, last: r.lastDay[t],
      };
    }).sort((a, b) => {
      const oa = a.trend ? PS.metrics.TREND_ORDER[a.trend.label] : 4;
      const ob = b.trend ? PS.metrics.TREND_ORDER[b.trend.label] : 4;
      return oa - ob || (b.trend ? b.trend.recentShare : 0) - (a.trend ? a.trend.recentShare : 0) ||
        b.docs.length - a.docs.length || name(a.t).localeCompare(name(b.t));
    });

    figure.subtitle.textContent =
      `Documents tagged with each theme${state.from || state.to ? " within the selected dates" : ""}, ` +
      `the ${scheme.name} with its highest share, its trend (as in Themes over time), and the people ` +
      `with the most activity on it. Choose a theme to list its commits, PRs, and issues.`;

    if (!themes.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No themed activity matches the filters."));
      figure.details.hidden = true;
      return;
    }

    if (figure.open === undefined) figure.open = PS.selectedTheme(state);
    const head = PS.el("tr", {}, ["Theme", "Trend", "Documents", "First seen", "Peak", "Last seen", "Top contributors"]
      .map(h => PS.el("th", {scope: "col"}, h)));
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
      return PS.el("tr", {class: x.t === PS.selectedTheme(state) ? "selected" : null},
        PS.el("td", {}, button),
        PS.el("td", {}, x.trend ? `${PS.trendText(x.trend)} (${pct(x.trend.recentShare)} vs ${pct(x.trend.earlierShare)})` : "–"),
        PS.el("td", {}, x.docs.length),
        PS.el("td", {}, x.first === null ? "–" : day(x.first)),
        PS.el("td", {}, x.peak ? `${x.peak.label} (${pct(x.peak.share)})` : "–"),
        PS.el("td", {}, x.last === null ? "–" : day(x.last)),
        PS.el("td", {class: "people"}, x.contributors
          .map(c => `${PS.personName(c.person)} ${c.code + c.discussion}`).join(", ") || "–"));
    });
    figure.plot.replaceChildren(PS.el("div", {class: "table-scroll"},
      PS.el("table", {class: "data themes"}, PS.el("thead", {}, head), PS.el("tbody", {}, body))));

    const open = themes.find(x => x.t === figure.open);
    figure.details.hidden = !open;
    if (!open) return;
    const filtered = PS.selectedTheme(state) === open.t;
    const filterButton = PS.el("button", {type: "button"},
      filtered ? "Show all themes on the page" : "Filter the page to this theme");
    filterButton.onclick = () => set({theme: filtered ? undefined : name(open.t)});
    const close = PS.el("button", {type: "button"}, "Close");
    close.onclick = () => {
      figure.open = null;
      this.render(figure, {data, rowsExcept, state, set});
    };
    const repo = data.project.github;
    const url = d => {
      const ref = data.docs.ref[d];
      const source = data.docs.source[d];
      return source === "pr" ? `https://github.com/${repo}/pull/${ref}`
        : source === "issue" ? `https://github.com/${repo}/issues/${ref}`
        : `https://github.com/${repo}/commit/${ref}`;
    };
    const kindName = {pr: "PR", issue: "issue", commit: "commit"};
    const {themesOf} = PS.metrics.themeIndex(data);
    const limit = figure.showAll ? open.docs.length : 50;
    const items = open.docs.slice(0, limit).map(d => {
      const others = (themesOf.get(d) || []).filter(t => t !== open.t).map(name);
      const ref = data.docs.source[d] === "commit" ? data.docs.ref[d].slice(0, 7) : `#${data.docs.ref[d]}`;
      return PS.el("li", {},
        PS.el("span", {class: "meta"}, `${day(data.docs.day[d])} · ${kindName[data.docs.source[d]] || data.docs.source[d]} ${ref}`),
        PS.el("a", {href: url(d)}, data.docs.title[d]),
        others.length ? PS.el("span", {class: "meta"}, `also: ${others.join(", ")}`) : null);
    });
    const more = open.docs.length > limit ? PS.el("button", {type: "button"}, `Show all ${open.docs.length}`) : null;
    if (more) {
      more.onclick = () => {
        figure.showAll = true;
        this.render(figure, {data, rowsExcept, state, set});
      };
    }
    figure.details.replaceChildren(
      PS.el("div", {class: "details-head"},
        PS.el("h3", {}, `${name(open.t)} · ${open.docs.length} document${open.docs.length === 1 ? "" : "s"}`),
        filterButton, close),
      open.contributors.length ? PS.el("p", {class: "meta"}, "Most active: " + open.contributors
        .map(c => `${PS.personName(c.person)} (${c.code} code, ${c.discussion} discussion)`).join(", ")) : null,
      PS.el("ul", {class: "doc-list"}, items),
      more);
  },
});
