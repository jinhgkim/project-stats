// Page core: the data, state kept in the URL hash, the filter/view registry,
// and helpers every view shares (periods, data-source markers, tooltip, DOM).
// Filters and views are separate files that call PS.registerFilter/View.

const PS = (() => {
  const data = JSON.parse(document.getElementById("data").textContent);
  const DAY_MS = 86400000;
  const FLAGS = new Set(["check"]);  // hash keys without a value
  const filters = [];
  const views = [];
  const startHooks = [];
  let state = {};

  // ---- state in the URL hash: #kinds=commit,pr&period=year&check -------------

  function readHash() {
    const out = {};
    for (const part of location.hash.replace(/^#/, "").split("&")) {
      if (!part) continue;
      const [key, value = ""] = part.split("=").map(decodeURIComponent);
      out[key] = FLAGS.has(key) ? true : value;
    }
    return out;
  }

  function writeHash() {
    const parts = [];
    for (const [key, value] of Object.entries(state)) {
      if (value === undefined || value === null || value === "" || value === false) continue;
      parts.push(value === true ? encodeURIComponent(key)
        : `${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
    history.replaceState(null, "", parts.length ? "#" + parts.join("&") : location.pathname);
  }

  function set(changes) {
    Object.assign(state, changes);
    for (const filter of filters) if (filter.sync) filter.sync(state);
    writeHash();
    renderAll();
  }

  // The keys the top-bar filters own, cleared by Reset.
  const FILTER_KEYS = ["from", "to", "kinds", "theme"];



  // ---- registry ---------------------------------------------------------------

  // filter: {id, init?(state), control(el, state, set), predicate?(state) -> (i) => bool,
  //          sync?(state), target?}; sync updates the control when another part
  //          of the page changes its state. A control with a `target` view id
  //          sits in that view instead of the top bar (settings, not filters).
  function registerFilter(filter) { filters.push(filter); }
  // view: {id, title, order, tab, width?, bare?, noTable?, render(figure, ctx)};
  // ctx = {data, rows, rowsExcept(filterId), state, set}. Views appear by
  // `order` within their tab. width "half" pairs views on wide screens.
  // A bare view has no card or title.
  function registerView(view) { views.push(view); }

  // Tabs, in order; the first is the default. Only the open tab's views are
  // drawn. An intro may depend on the data.
  const TABS = [
    {id: "overview", label: "Overview",
     intro: () => "The headline numbers, and how many people contribute over time."},
    {id: "people", label: "People",
     intro: () => "Who contributes, how often, and for how long. Activity means commits, " +
       "PRs opened, reviews, issues opened, and comments."},
    {id: "themes", label: "Themes",
     intro: () => {
       const days = data.themes.tagged.map(d => data.docs.day[d]);
       return "What the work is about. A local language model tagged each commit, PR, and " +
         "issue with up to 3 themes" +
         (days.length ? `; tags cover documents from ${dayToText(Math.min(...days))} on.` : ".");
     }},
  ];
  const tabOf = view => view.tab || TABS[0].id;
  function activeTab() {
    return TABS.some(t => t.id === state.tab) ? state.tab : TABS[0].id;
  }
  function onStart(fn) { startHooks.push(fn); }

  // Activity row indexes passing every filter (except the one named `skip`).
  function filteredRows(skip) {
    const tests = filters.filter(f => f.id !== skip)
      .map(f => f.predicate && f.predicate(state)).filter(Boolean);
    const n = data.activity.day.length;
    const rows = [];
    outer: for (let i = 0; i < n; i++) {
      for (const test of tests) if (!test(i)) continue outer;
      rows.push(i);
    }
    return rows;
  }

  function renderAll() {
    const except = new Map();
    const rowsExcept = id => {
      if (!except.has(id)) except.set(id, filteredRows(id));
      return except.get(id);
    };
    const ctx = {data, rows: filteredRows(), rowsExcept, state, set};
    const reset = document.getElementById("reset");
    if (reset) reset.disabled = !FILTER_KEYS.some(k => state[k] !== undefined);
    const open = activeTab();
    for (const tab of TABS) {
      if (!tab.button) continue;
      const selected = tab.id === open;
      tab.button.setAttribute("aria-selected", String(selected));
      tab.button.tabIndex = selected ? 0 : -1;
      tab.panel.hidden = !selected;
    }
    for (const view of views) {
      if (tabOf(view) !== open) continue;
      try {
        view.render(view.figure, ctx);
      } catch (err) {
        console.error(err);
        view.figure.plot.replaceChildren(el("p", {class: "empty"}, `Error: ${err.message}`));
      }
    }
  }

  // ---- DOM helpers (text always goes in as textContent) -----------------------

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "onclick" || key === "onchange" || key === "oninput") node[key] = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function makeFigure(view) {
    const tableButton = el("button", {type: "button", "aria-pressed": "false", "data-label": "Table"}, "Table");
    const classes = ["view", view.width, view.bare ? "bare" : null].filter(Boolean).join(" ");
    const howtoBody = el("div", {class: "howto-body"});
    const figure = {
      root: el("figure", {class: classes, id: `view-${view.id}`}),
      subtitle: el("p", {class: "subtitle"}),
      howto: el("details", {class: "howto", hidden: true}, el("summary", {}, "How to read this"), howtoBody),
      howtoBody,
      controls: el("div", {class: "controls"}),
      legend: el("div", {class: "legend"}),
      plot: el("div", {class: "plot"}),
      table: el("div", {class: "table-wrap", hidden: true}),
      details: el("div", {class: "details", hidden: true}),
      showTable: false,
    };
    tableButton.onclick = () => {
      figure.showTable = !figure.showTable;
      tableButton.setAttribute("aria-pressed", String(figure.showTable));
      figure.table.hidden = !figure.showTable;
      figure.plot.hidden = figure.showTable;
      figure.legend.hidden = figure.showTable;
    };
    if (view.bare) {
      figure.root.append(figure.plot);
      return figure;
    }
    figure.root.append(
      el("div", {class: "head"}, el("h3", {}, view.title), view.noTable ? null : tableButton),
      figure.subtitle, figure.howto, figure.controls, figure.legend, figure.plot, figure.table, figure.details,
    );
    return figure;
  }

  // The collapsed "How to read this" under a view's question: a list of
  // short definitions. Its open state survives re-renders.
  function fillHowto(figure, items) {
    figure.howto.hidden = !items.length;
    figure.howtoBody.replaceChildren(el("ul", {}, items.map(item => el("li", {}, item))));
  }

  // Open the tab holding a view (by its element id) and scroll to it, clear
  // of the pinned bar.
  function jumpTo(id) {
    const view = views.find(v => `view-${v.id}` === id);
    if (view && tabOf(view) !== activeTab()) openTab(tabOf(view));
    const node = document.getElementById(id);
    if (node) requestAnimationFrame(() => node.scrollIntoView({behavior: "smooth", block: "start"}));
  }

  function openTab(id) {
    set({tab: id === TABS[0].id ? undefined : id});
  }

  // columns: [{name, value(row)}]; a "Table" toggle shows it instead of the plot.
  function fillTable(figure, columns, rows) {
    const head = el("tr", {}, columns.map(c => el("th", {scope: "col"}, c.name)));
    const body = rows.map(r => el("tr", {}, columns.map(c => {
      const v = c.value(r);
      return el("td", {}, v === null || v === undefined ? "–" : v);
    })));
    figure.table.replaceChildren(el("table", {class: "data"}, el("thead", {}, head), el("tbody", {}, body)));
  }

  // keys: [{name, color, shape: "rect"|"line"}]
  function fillLegend(figure, keys) {
    figure.legend.replaceChildren(...keys.map(k => el("span", {class: "key"}, swatch(k), k.name)));
  }

  function swatch(key) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "10");
    const mark = document.createElementNS(ns, key.shape === "line" ? "line" : "rect");
    if (key.shape === "line") {
      Object.entries({x1: 0, x2: 14, y1: 5, y2: 5, stroke: key.color, "stroke-width": 2,
        "stroke-linecap": "round"}).forEach(([a, v]) => mark.setAttribute(a, v));
    } else {
      Object.entries({x: 1, y: 0, width: 12, height: 10, rx: 2, fill: key.color})
        .forEach(([a, v]) => mark.setAttribute(a, v));
    }
    svg.append(mark);
    return svg;
  }

  // Keyboard for a list of marks: one tab stop (at index `current`); the
  // prev/next keys, Home, and End move focus between them.
  function rovingFocus(nodes, current, prevKey, nextKey) {
    nodes.forEach((node, i) => {
      node.setAttribute("tabindex", i === current ? 0 : -1);
      node.addEventListener("keydown", event => {
        const to = {[prevKey]: i - 1, [nextKey]: i + 1, Home: 0, End: nodes.length - 1}[event.key];
        if (to === undefined) return;
        event.preventDefault();
        const j = Math.max(0, Math.min(nodes.length - 1, to));
        node.setAttribute("tabindex", -1);
        nodes[j].setAttribute("tabindex", 0);
        nodes[j].focus();
      });
    });
  }

  // A person's display name, and a GitHub profile link when a login is known.
  function personName(i) { return data.people.name[i] || data.people.login[i] || `#${i}`; }
  function personLink(i) {
    const login = data.people.login[i];
    return login ? el("a", {href: `https://github.com/${login}`}, personName(i)) : personName(i);
  }

  // ---- tooltip ------------------------------------------------------------------

  const tooltip = document.getElementById("tooltip");

  // rows: [{name, value, color?}]; the value leads, the name follows.
  function showTooltip(anchor, title, rows) {
    tooltip.replaceChildren(
      el("div", {class: "title"}, title),
      ...rows.map(r => el("div", {class: "row"},
        r.color ? swatch({color: r.color, shape: "line"}) : el("span", {style: "width:14px"}),
        el("span", {class: "value"}, r.value),
        el("span", {class: "name"}, r.name))),
    );
    tooltip.style.display = "block";
    const box = tooltip.getBoundingClientRect();
    let x, y;
    if (anchor instanceof Event && "clientX" in anchor) {
      x = anchor.clientX + 14;
      y = anchor.clientY + 14;
    } else {
      const r = anchor.getBoundingClientRect();
      x = r.right + 8;
      y = r.top;
    }
    if (x + box.width > window.innerWidth - 8) x = Math.max(8, x - box.width - 28);
    if (y + box.height > window.innerHeight - 8) y = Math.max(8, window.innerHeight - box.height - 8);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  }

  function hideTooltip() { tooltip.style.display = "none"; }

  // Width in px of text drawn at `size` px in the page font, for fitting labels.
  const measure = document.createElement("canvas").getContext("2d");
  function textWidth(text, size) {
    measure.font = `${size}px ${getComputedStyle(document.body).fontFamily}`;
    return measure.measureText(text).width;
  }

  // ---- time: whole days since 1970-01-01 (UTC) -------------------------------

  function dayToDate(day) { return new Date(day * DAY_MS); }
  function dateToDay(text) { return Math.floor(Date.parse(`${text}T00:00:00Z`) / DAY_MS); }
  function dayToText(day) { return dayToDate(day).toISOString().slice(0, 10); }
  function monthIndex(day) { const d = dayToDate(day); return d.getUTCFullYear() * 12 + d.getUTCMonth(); }
  function monthStart(index) { return Date.UTC(Math.floor(index / 12), index % 12, 1) / DAY_MS; }

  function bisectRight(sorted, x) {
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (x < sorted[mid]) hi = mid; else lo = mid + 1;
    }
    return lo;
  }

  const MONTHS = {month: 1, quarter: 3, year: 12};
  const PERIOD_NAMES = {month: "month", quarter: "quarter", year: "year", release: "release cycle"};

  // A period scheme maps a day to a period key, and keys to labels and bounds.
  // Months, quarters, and years match projstats/retention.py; release cycles
  // match projstats/documents.py release_periods().
  function periodScheme(kind) {
    if (kind === "release") {
      const days = data.releases.day;
      const versions = data.releases.version;
      const last = days.length;
      return {
        kind, name: PERIOD_NAMES[kind],
        key: day => bisectRight(days, day),
        label: k => (k < last ? `${versions[k]} cycle` : `after ${versions[last - 1]}`),
        short: k => (k < last ? versions[k] : `after ${versions[last - 1]}`),
        bounds: k => [k === 0 ? null : days[k - 1], k < last ? days[k] : null],
      };
    }
    const n = MONTHS[kind];
    const label = k => (kind === "month"
      ? `${Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, "0")}`
      : kind === "quarter" ? `${Math.floor(k / 4)}Q${(k % 4) + 1}` : String(k));
    return {
      kind, name: PERIOD_NAMES[kind],
      key: day => Math.floor(monthIndex(day) / n),
      label, short: label,
      bounds: k => [monthStart(k * n), monthStart((k + 1) * n)],
    };
  }

  // Where each included activity kind's data starts (except the earliest),
  // so a jump caused by a new data source isn't read as growth.
  const KIND_NAMES = {commit: "commits", pr: "PRs", review: "reviews", issue: "issues", comment: "comments"};
  function sourceMarkers(kinds) {
    const byDay = new Map();
    for (const kind of kinds) {
      const day = data.sources[kind];
      if (day === undefined) continue;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(KIND_NAMES[kind] || kind);
    }
    // Sources starting within a month of each other share one marker.
    const merged = [];
    for (const day of [...byDay.keys()].sort((a, b) => a - b)) {
      const prev = merged[merged.length - 1];
      if (prev && day - prev.day < 31) prev.names.push(...byDay.get(day));
      else merged.push({day, names: [...byDay.get(day)]});
    }
    return merged.slice(1).map(m => ({day: m.day, label: `${m.names.join(", ")} start`}));
  }

  // Labels for sourceMarkers(), stacked 14px apart from y0 and kept between
  // minX and maxX (next to their line when there is room).
  function markerLabels(g, markers, x, y0, minX, maxX) {
    markers.forEach((m, i) => {
      const w = textWidth(m.label, 11);
      const left = Math.max(minX, Math.min(x(m.key) + 4, maxX - w));
      g.append("text").attr("x", left).attr("y", y0 + i * 14).text(m.label);
    });
  }

  // Text cut with "…" to fit `max` px at `size` px.
  function fitText(text, size, max) {
    if (textWidth(text, size) <= max) return text;
    let n = text.length;
    while (n > 1 && textWidth(`${text.slice(0, n)}…`, size) > max) n -= 1;
    return `${text.slice(0, n)}…`;
  }

  function selectedKinds() {
    return state.kinds ? state.kinds.split(",").filter(k => data.kinds.includes(k)) : data.kinds.slice();
  }

  // ---- start ----------------------------------------------------------------------

  const THEMES = ["auto", "light", "dark"];
  function applyTheme() {
    const theme = THEMES.includes(state.theme) ? state.theme : "auto";
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    document.getElementById("theme").textContent = `Theme: ${theme}`;
  }

  function start() {
    state = readHash();
    const p = data.project;
    const meta = document.getElementById("meta");
    meta.textContent =
      `${p.github} · data through ${p.data_end === null ? "–" : dayToText(p.data_end)} · built ${p.generated}`;
    const excluded = p.excluded_items || [];
    if (excluded.length) {
      meta.append(" · left out of counts: ", ...excluded.flatMap((n, i) => [
        i ? ", " : "", el("a", {href: `https://github.com/${p.github}/issues/${n}`}, `#${n}`)]));
    }
    const themeButton = document.getElementById("theme");
    themeButton.onclick = () => {
      const next = THEMES[(THEMES.indexOf(state.theme || "auto") + 1) % THEMES.length];
      state.theme = next === "auto" ? undefined : next;
      applyTheme();
      writeHash();
      renderAll();
    };
    applyTheme();

    // Tabs: a tab list at the bottom of the pinned bar, right above the
    // panels. Arrow keys, Home, and End move between tabs and open them.
    const main = document.getElementById("views");
    const tabList = document.getElementById("tabs");
    views.sort((a, b) => (a.order || 0) - (b.order || 0));
    const tabs = TABS.filter(tab => views.some(v => tabOf(v) === tab.id));
    tabs.forEach((tab, i) => {
      const grid = el("div", {class: "grid"});
      tab.button = el("button", {
        type: "button", role: "tab", class: "tab", id: `tab-${tab.id}`,
        "aria-controls": `panel-${tab.id}`, "data-label": tab.label,
      }, tab.label);
      tab.button.onclick = () => openTab(tab.id);
      tab.button.addEventListener("keydown", event => {
        const to = {ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1}[event.key];
        if (to === undefined) return;
        event.preventDefault();
        const next = tabs[(to + tabs.length) % tabs.length];
        openTab(next.id);
        next.button.focus();
      });
      tab.panel = el("section", {
        class: "panel", id: `panel-${tab.id}`, role: "tabpanel", "aria-labelledby": `tab-${tab.id}`,
      }, el("p", {class: "intro"}, tab.intro()), grid);
      for (const view of views.filter(v => tabOf(v) === tab.id)) {
        view.figure = makeFigure(view);
        grid.append(view.figure.root);
      }
      tabList.append(tab.button);
      main.append(tab.panel);
    });

    const bar = document.getElementById("filter-controls");
    for (const filter of filters) {
      if (filter.init) filter.init(state);
      const box = el("div", {class: "filter", id: `filter-${filter.id}`});
      filter.control(box, state, set);
      const target = filter.target && views.find(v => v.id === filter.target);
      if (target) target.figure.controls.append(box);
      else bar.append(box);
    }
    bar.append(el("button", {
      type: "button", id: "reset", onclick: () => set(Object.fromEntries(FILTER_KEYS.map(k => [k, undefined]))),
    }, "Reset filters"));

    // Sections scroll clear of the pinned bar.
    const barNode = document.getElementById("filters");
    const updateBar = () => document.documentElement.style.setProperty("--bar-h", `${barNode.offsetHeight}px`);
    updateBar();
    window.addEventListener("resize", updateBar);
    writeHash();
    renderAll();
    for (const hook of startHooks) hook();

    let pending = null;
    window.addEventListener("resize", () => {
      clearTimeout(pending);
      pending = setTimeout(renderAll, 150);
    });
    window.addEventListener("scroll", hideTooltip, {passive: true});
  }

  return {
    data, get state() { return state; }, set, start,
    registerFilter, registerView, onStart,
    el, fillTable, fillLegend, fillHowto, jumpTo, openTab, showTooltip, hideTooltip, textWidth, rovingFocus,
    personName, personLink, dayToDate,
    dayToText, dateToDay, periodScheme, sourceMarkers, markerLabels, fitText, selectedKinds, KIND_NAMES,
  };
})();
