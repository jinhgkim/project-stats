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
    writeHash();
    renderAll();
  }

  // ---- registry ---------------------------------------------------------------

  // filter: {id, init?(state), control(el, state, set), predicate?(state) -> (i) => bool}
  function registerFilter(filter) { filters.push(filter); }
  // view: {id, title, render(figure, ctx)}; ctx = {data, rows, state, set}
  function registerView(view) { views.push(view); }
  function onStart(fn) { startHooks.push(fn); }

  function filteredRows() {
    const tests = filters.map(f => f.predicate && f.predicate(state)).filter(Boolean);
    const n = data.activity.day.length;
    const rows = [];
    outer: for (let i = 0; i < n; i++) {
      for (const test of tests) if (!test(i)) continue outer;
      rows.push(i);
    }
    return rows;
  }

  function renderAll() {
    const ctx = {data, rows: filteredRows(), state, set};
    for (const view of views) {
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
    const figure = {
      root: el("figure", {class: "view", id: `view-${view.id}`}),
      subtitle: el("p", {class: "subtitle"}),
      legend: el("div", {class: "legend"}),
      plot: el("div", {class: "plot"}),
      table: el("div", {class: "table-wrap", hidden: true}),
      showTable: false,
    };
    tableButton.onclick = () => {
      figure.showTable = !figure.showTable;
      tableButton.setAttribute("aria-pressed", String(figure.showTable));
      figure.table.hidden = !figure.showTable;
      figure.plot.hidden = figure.showTable;
      figure.legend.hidden = figure.showTable;
    };
    figure.root.append(
      el("div", {class: "head"}, el("h2", {}, view.title), tableButton),
      figure.subtitle, figure.legend, figure.plot, figure.table,
    );
    return figure;
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

    const bar = document.getElementById("filters");
    for (const filter of filters) {
      if (filter.init) filter.init(state);
      const box = el("div", {class: "filter", id: `filter-${filter.id}`});
      filter.control(box, state, set);
      bar.append(box);
    }
    const main = document.getElementById("views");
    for (const view of views) {
      view.figure = makeFigure(view);
      main.append(view.figure.root);
    }
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
    el, fillTable, fillLegend, showTooltip, hideTooltip, textWidth,
    dayToText, dateToDay, periodScheme, sourceMarkers, selectedKinds, KIND_NAMES,
  };
})();
