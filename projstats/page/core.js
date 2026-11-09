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

  // The hash for a state, without the keys in `skip`.
  function hashOf(s, skip = []) {
    const parts = [];
    for (const [key, value] of Object.entries(s)) {
      if (skip.includes(key) || value === undefined || value === null || value === "" || value === false) continue;
      parts.push(value === true ? encodeURIComponent(key)
        : `${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
    return parts.length ? "#" + parts.join("&") : "";
  }

  function writeHash() {
    history.replaceState(null, "", hashOf(state) || location.pathname);
  }

  function set(changes) {
    Object.assign(state, changes);
    for (const filter of filters) if (filter.sync) filter.sync(state);
    writeHash();
    renderAll();
  }

  // ---- registry ---------------------------------------------------------------

  // filter: {id, keys?, projectKeys?, init?(state), control(el, state, set),
  //          predicate?(state) -> (i) => bool, sync?(state), target?, secondary?,
  //          chips?(state)}. keys: the URL keys it owns, cleared by Reset all.
  //          projectKeys: keys that name one project's data (people, themes),
  //          dropped when switching projects. sync updates the control when
  //          another part of the page changes its state. A control with a
  //          `target` view id sits in that view instead of the top bar
  //          (settings, not filters). A `secondary` control waits behind "More
  //          filters". chips(state) lists [{text, clear}] for what the filter
  //          changes now; clear is the state patch that undoes it.
  function registerFilter(filter) { if (featureOn(filter)) filters.push(filter); }
  // A filter or view with a `feature` (e.g. "themes") exists only when
  // data.features turns it on.
  const featureOn = item => !item.feature || Boolean(data.features[item.feature]);
  // view: {id, title, order, tab?, feature?, projectKeys?, width?, bare?, noTable?,
  // render(figure, ctx)}; ctx = {data, rows, rowsExcept(filterId), state, set}.
  // Views appear by `order` within their tab; one without `tab` goes on the
  // first tab. width "half" pairs views on wide screens. A bare view has no
  // card or title.
  function registerView(view) { if (featureOn(view)) views.push(view); }

  // tab: {id, label, order}. Tabs appear by `order`, and only when some view
  // is on them; the first is the default. Only the open tab's views are drawn.
  const tabRegistry = [];
  function registerTab(tab) { tabRegistry.push(tab); }
  registerTab({id: "overview", label: "Overview", order: 10});
  registerTab({id: "people", label: "People", order: 20});
  registerTab({id: "themes", label: "Themes", order: 30});
  let TABS = [];  // the tabs shown, set at start
  let firstTab = null;
  const tabOf = view => view.tab || firstTab;
  function activeTab() {
    return TABS.some(t => t.id === state.tab && views.some(v => tabOf(v) === t.id)) ? state.tab : TABS[0].id;
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

  // One removable chip per filter that is narrowing the data, then Reset all.
  // The badge on "More filters" counts the chips of filters kept behind it.
  function renderChips() {
    const box = document.getElementById("filter-chips");
    const chips = filters.flatMap(f => (f.chips ? f.chips(state) : []).map(c => ({...c, secondary: f.secondary})));
    const badge = document.getElementById("more-badge");
    if (badge) {
      const hidden = chips.filter(c => c.secondary).length;
      badge.hidden = !hidden;
      badge.textContent = hidden;
    }
    box.hidden = !chips.length;
    box.replaceChildren();
    if (!chips.length) return;
    box.append(el("span", {class: "label"}, "Filtered by"));
    for (const c of chips) {
      box.append(el("span", {class: "chip"}, c.text, el("button", {
        type: "button", "aria-label": `Remove filter: ${c.text}`, onclick: () => set(c.clear),
      }, "×")));
    }
    box.append(el("button", {
      type: "button", class: "link",
      onclick: () => set(Object.fromEntries(filters.flatMap(f => f.keys || []).map(k => [k, undefined]))),
    }, "Reset all"));
  }

  function renderAll() {
    const except = new Map();
    const rowsExcept = id => {
      if (!except.has(id)) except.set(id, filteredRows(id));
      return except.get(id);
    };
    const ctx = {data, rows: filteredRows(), rowsExcept, state, set};
    renderChips();
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
      tableNote: el("div", {class: "legend", hidden: true}),
      plot: el("div", {class: "plot"}),
      table: el("div", {class: "table-wrap", hidden: true}),
      details: el("div", {class: "details", id: `details-${view.id}`, hidden: true}),
      showTable: false,
    };
    tableButton.onclick = () => {
      figure.showTable = !figure.showTable;
      tableButton.setAttribute("aria-pressed", String(figure.showTable));
      figure.table.hidden = !figure.showTable;
      figure.plot.hidden = figure.showTable;
      figure.legend.hidden = figure.showTable;
      figure.tableNote.hidden = !figure.showTable || !figure.tableNote.hasChildNodes();
    };
    if (view.bare) {
      figure.root.append(figure.plot);
      return figure;
    }
    figure.root.append(
      el("div", {class: "head"}, el("h3", {}, view.title), view.noTable ? null : tableButton),
      figure.subtitle, figure.howto, figure.controls, figure.legend, figure.tableNote, figure.plot, figure.table,
      figure.details,
    );
    return figure;
  }

  // The collapsed "How to read this" under a view's question: a list of
  // short definitions. Its open state survives re-renders.
  function fillHowto(figure, items) {
    figure.howto.hidden = !items.length;
    figure.howtoBody.replaceChildren(el("ul", {}, items.map(item => el("li", {}, item))));
  }

  // Open the tab holding a view or its details area (by element id), apply
  // any state `changes` (e.g. which list to show), and scroll there, clear of
  // the pinned bar.
  function jumpTo(id, changes = {}) {
    const view = views.find(v => id === `view-${v.id}` || id === `details-${v.id}`);
    const tab = view ? tabOf(view) : activeTab();
    if (tab !== activeTab() || Object.keys(changes).length) {
      set({...changes, tab: tab === TABS[0].id ? undefined : tab});
    }
    const node = document.getElementById(id);
    if (node) requestAnimationFrame(() => node.scrollIntoView({behavior: "smooth", block: "start"}));
  }

  function openTab(id) {
    set({tab: id === TABS[0].id ? undefined : id});
  }

  // columns: [{name, value(row)}]; a "Table" toggle shows it instead of the plot.
  // unit: shown at the right above the table, in place of units in the cells.
  function fillTable(figure, columns, rows, unit) {
    figure.tableNote.replaceChildren(...(unit ? [el("span", {class: "unit"}, unit)] : []));
    figure.tableNote.hidden = !figure.showTable || !unit;
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

  // The GitHub page of a document (PR, issue, or commit) of this project.
  function docUrl(d) {
    const repo = data.project.github;
    const ref = data.docs.ref[d];
    const source = data.docs.source[d];
    return source === "pr" ? `https://github.com/${repo}/pull/${ref}`
      : source === "issue" ? `https://github.com/${repo}/issues/${ref}`
      : `https://github.com/${repo}/commit/${ref}`;
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

  // Hover hints. The browser's own `title` tooltip waits about a second and
  // often goes unseen, so the first hover moves the text to data-tip (and
  // aria-description) and shows it in the page tooltip after a short pause.
  function setupHints() {
    let current = null;
    let timer = null;
    const hide = () => {
      clearTimeout(timer);
      current = null;
      hideTooltip();
    };
    document.addEventListener("mouseover", event => {
      const target = event.target.closest("[title], [data-tip]");
      if (!target || target === current) return;
      hide();
      const text = target.dataset.tip || target.getAttribute("title");
      if (!text) return;
      if (target.hasAttribute("title")) {
        target.dataset.tip = text;
        target.setAttribute("aria-description", text);
        target.removeAttribute("title");
      }
      current = target;
      timer = setTimeout(() => showTooltip(event, text, []), 120);
    });
    document.addEventListener("mouseout", event => {
      if (current && !current.contains(event.relatedTarget)) hide();
    });
    document.addEventListener("mousedown", hide);
  }

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
  // "3.2" -> "3.3 dev" (matches projstats/releases.py next_version).
  function openName(version) {
    const [major, minor] = version.split(".");
    return /^\d+$/.test(major) && /^\d+$/.test(minor) ? `${major}.${Number(minor) + 1} dev` : `after ${version}`;
  }

  function periodScheme(kind) {
    if (kind === "release") {
      const days = data.releases.day;
      const versions = data.releases.version;
      const last = days.length;
      return {
        kind, name: PERIOD_NAMES[kind],
        key: day => bisectRight(days, day),
        // The cycle in progress is named for the next version, so it needs no "so far".
        label: k => (k < last ? versions[k] : openName(versions[last - 1])),
        short: k => (k < last ? versions[k] : openName(versions[last - 1])),
        soFar: false,
        bounds: k => [k === 0 ? null : days[k - 1], k < last ? days[k] : null],
      };
    }
    const n = MONTHS[kind];
    const label = k => (kind === "month"
      ? `${Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, "0")}`
      : kind === "quarter" ? `${Math.floor(k / 4)} Q${(k % 4) + 1}` : String(k));
    return {
      kind, name: PERIOD_NAMES[kind],
      key: day => Math.floor(monthIndex(day) / n),
      label, short: label, soFar: true,
      bounds: k => [monthStart(k * n), monthStart((k + 1) * n)],
    };
  }

  // A date range that starts or ends inside a period leaves it partial too:
  // marks `cut` on each such period (rows with `key` and `partial`, from a
  // scheme). The period holding the data's end is partial; a range that ends
  // earlier leaves that period out, so its mark is cleared.
  function markRangeCuts(periods, scheme, state) {
    const lo = state.from ? dateToDay(state.from) : null;
    const hi = state.to ? dateToDay(state.to) : null;
    if (lo === null && hi === null) return;
    const first = Math.min(...Object.values(data.sources));
    const end = data.project.data_end;
    for (const p of periods) {
      if (hi !== null && hi < end) p.partial = false;
      const [start, stop] = scheme.bounds(p.key);
      p.cut = (lo !== null && lo > Math.max(start === null ? -Infinity : start, first)) ||
        (hi !== null && hi < Math.min(stop === null ? Infinity : stop - 1, end));
    }
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

  // Color theme: one button showing the current choice's icon; each click
  // moves to the next of system (auto), light, and dark.
  const THEMES = ["auto", "light", "dark"];
  const THEME_ICONS = {
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4' +
      'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    auto: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    dark: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  };
  const THEME_NAMES = {light: "Light", auto: "System", dark: "Dark"};
  function applyTheme() {
    const theme = THEMES.includes(state.colors) ? state.colors : "auto";
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    const button = document.getElementById("theme");
    const label = `${THEME_NAMES[theme]} theme (click for ${THEME_NAMES[next].toLowerCase()})`;
    button.setAttribute("aria-label", label);
    button.title = label;
    // Fixed icon markup from THEME_ICONS, never data.
    button.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
      `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${THEME_ICONS[theme]}</svg>`;
  }

  // Other projects' pages sit next to this one (data.siblings, set when the
  // page is built). The title ends with the dropdown: Project Analytics: [name].
  // Switching keeps the view except what belongs to one project (projectKeys).
  function setupProjectSwitch() {
    const select = document.getElementById("project");
    const projects = data.siblings || [];
    if (projects.length < 2) return;
    select.append(...projects.map((s, i) => el("option", {value: i}, s.name)));
    const current = projects.findIndex(s => s.current);
    select.value = current;
    const title = document.getElementById("title");
    const pick = el("span", {class: "project-pick"});
    select.replaceWith(pick);
    pick.append(select);
    if (title.textContent.startsWith(projects[current].name)) {
      // "Project Analytics: [name]", so the fixed text never moves between projects.
      title.replaceChildren(`${title.textContent.slice(projects[current].name.length).trim()}:`, pick);
      // Fit the select to the open project's name, not the longest one:
      // text, left padding, the arrow's room on the right, and the border.
      const ctx = document.createElement("canvas").getContext("2d");
      ctx.font = `600 20px ${getComputedStyle(document.body).fontFamily}`;
      select.style.width = `${Math.ceil(ctx.measureText(projects[current].name).width) + 44}px`;
    }
    select.onchange = () => {
      const target = projects[select.value];
      if (target.current) return;
      location.href = target.href + hashOf(state, [...filters, ...views].flatMap(x => x.projectKeys || []));
    };
    select.hidden = false;
  }

  function start() {
    state = readHash();
    const p = data.project;
    const longDate = d => new Date(d * DAY_MS).toLocaleDateString("en-US",
      {year: "numeric", month: "short", day: "numeric", timeZone: "UTC"});
    const about = document.getElementById("about");
    about.title = `Page built ${longDate(dateToDay(p.generated))}`;
    about.append(`Data from `, el("a", {href: `https://github.com/${p.github}`}, p.label || p.github),
      `, through ${p.data_end === null ? "–" : longDate(p.data_end)}`);
    document.getElementById("theme").onclick = () => {
      const theme = THEMES.includes(state.colors) ? state.colors : "auto";
      const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
      state.colors = next === "auto" ? undefined : next;
      applyTheme();
      writeHash();
      renderAll();
    };
    applyTheme();
    setupHints();
    setupProjectSwitch();

    // Tabs: a tab list at the bottom of the pinned bar, right above the
    // panels. Arrow keys, Home, and End move between tabs and open them.
    const main = document.getElementById("views");
    const tabList = document.getElementById("tabs");
    views.sort((a, b) => (a.order || 0) - (b.order || 0));
    tabRegistry.sort((a, b) => (a.order || 0) - (b.order || 0));
    firstTab = tabRegistry[0].id;
    TABS = tabRegistry.filter(tab => views.some(v => tabOf(v) === tab.id));
    TABS.forEach((tab, i) => {
      const grid = el("div", {class: "grid"});
      tab.button = el("button", {
        type: "button", role: "tab", class: "tab", id: `tab-${tab.id}`,
        "aria-controls": `panel-${tab.id}`, "data-label": tab.label,
      }, tab.label);
      tab.button.onclick = () => openTab(tab.id);
      tab.button.addEventListener("keydown", event => {
        const to = {ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1}[event.key];
        if (to === undefined) return;
        event.preventDefault();
        const next = TABS[(to + TABS.length) % TABS.length];
        openTab(next.id);
        next.button.focus();
      });
      tab.panel = el("section", {
        class: "panel", id: `panel-${tab.id}`, role: "tabpanel", "aria-labelledby": `tab-${tab.id}`,
      }, grid);
      for (const view of views.filter(v => tabOf(v) === tab.id)) {
        view.figure = makeFigure(view);
        grid.append(view.figure.root);
      }
      tabList.append(tab.button);
      main.append(tab.panel);
    });

    const bar = document.getElementById("filter-controls");
    const more = document.getElementById("filter-more");
    for (const filter of filters) {
      if (filter.init) filter.init(state);
      const box = el("div", {class: "filter", id: `filter-${filter.id}`});
      filter.control(box, state, set);
      const target = filter.target && views.find(v => v.id === filter.target);
      if (target) target.figure.controls.append(box);
      else if (filter.secondary) {
        if (box.childElementCount) more.append(box);
      } else bar.append(box);
    }
    if (more.childElementCount) {
      const toggle = el("button", {
        type: "button", id: "more-toggle", "aria-expanded": "true", "aria-controls": "filter-more",
      }, "More filters", el("span", {class: "badge", id: "more-badge", hidden: true}), el("span", {class: "chev", "aria-hidden": "true"}));
      more.hidden = false;
      toggle.onclick = () => {
        const opening = more.hidden;
        more.hidden = !opening;
        toggle.setAttribute("aria-expanded", String(opening));
      };
      bar.append(toggle);
    }

    // Sections scroll clear of the pinned bar, which grows when the extra
    // filters open or chips appear.
    const barNode = document.getElementById("filters");
    new ResizeObserver(() => {
      document.documentElement.style.setProperty("--bar-h", `${barNode.offsetHeight}px`);
    }).observe(barNode);
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
    registerFilter, registerView, registerTab, onStart,
    el, fillTable, fillLegend, swatch, fillHowto, jumpTo, openTab, showTooltip, hideTooltip, textWidth, rovingFocus,
    personName, personLink, docUrl, dayToDate,
    dayToText, dateToDay, periodScheme, markRangeCuts, sourceMarkers, markerLabels, fitText, selectedKinds, KIND_NAMES,
  };
})();
