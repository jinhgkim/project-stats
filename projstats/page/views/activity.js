// View: the activity of one person. Choosing a name opens that person's pane
// (their index in the URL) and choosing another replaces it. The Overview's pane
// (`who`) sits under the contributors list and shows the open column (`pick`),
// so it stays hidden until it is set. The People tab's pane (`pwho`) sits under
// the people list and shows everything the filters leave.

const KIND_LABELS = {commit: "Commit", pr: "PR opened", review: "Review", issue: "Issue opened", comment: "Comment"};
// Code and Discussion are the groups of the Activity filter (filters/kind.js),
// told apart by the color of the People tab's status dot.
const GROUPS = [
  {name: "Code", kinds: KIND_GROUPS.code, color: "var(--kind-code)"},
  {name: "Discussion", kinds: KIND_GROUPS.discussion, color: "var(--kind-discussion)"},
];
const groupOf = (kind, groups = GROUPS) => groups.find(g => g.kinds.includes(kind));
const dot = group => PS.el("span", {
  class: "status on", style: `background: ${group.color}; border-color: ${group.color}`, "aria-hidden": "true",
});
const KIND_NAMES = {
  commit: ["commit", "commits"], pr: ["PR opened", "PRs opened"], review: ["review", "reviews"],
  issue: ["issue opened", "issues opened"], comment: ["comment", "comments"],
};
const kindName = (kind, n) => (KIND_NAMES[kind] || [kind, kind])[n === 1 ? 0 : 1];

const LIMIT = 50;

// The person chosen under URL key `who` or `pwho`, or undefined.
PS.whoPick = (state, key = "who") => {
  const s = (state[key] || "").split(",")[0];
  const person = /^\d+$/.test(s) ? Number(s) : undefined;
  return person < PS.data.people.name.length ? person : undefined;
};

// The state change that picks a person, or drops them when already picked.
PS.whoToggle = (state, person, key = "who") =>
  ({[key]: PS.whoPick(state, key) === person ? undefined : String(person)});

// A name that opens that person's pane (`prefix` "people-" for the People tab's).
PS.personButton = (person, state, prefix = "") => {
  const key = prefix ? "pwho" : "who";
  return PS.el("button", {
    type: "button", class: "link-button", "aria-expanded": String(PS.whoPick(state, key) === person),
    onclick: () => {
      const patch = PS.whoToggle(state, person, key);
      if (patch[key] === undefined) PS.set(patch);
      else PS.jumpTo(`view-${prefix}activity`, patch);
    },
  }, PS.personName(person));
};

// Legend keys for activity rows: one per group (Code, Discussion), with its counts.
PS.activityKeys = (rows, groups = GROUPS) => {
  const A = PS.data.activity;
  const counts = new Map();
  for (const i of rows) counts.set(A.kind[i], (counts.get(A.kind[i]) || 0) + 1);
  const num = n => n.toLocaleString("en-US");
  return groups.map(g => {
    const inGroup = [...counts].filter(([k]) => g.kinds.includes(PS.data.kinds[k])).sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    if (!inGroup.length) return null;
    const detail = inGroup.map(([k, n]) => `${num(n)} ${kindName(PS.data.kinds[k], n)}`).join(", ");
    return PS.el("span", {class: "key"}, dot(g),
      `${g.name} ${num(inGroup.reduce((sum, [, n]) => sum + n, 0))} (${detail})`);
  }).filter(Boolean);
};

// The line above an activity table, for both panes that list one: the total,
// then the keys with their counts. Returns the nodes to put in a `.legend`.
PS.activitySummary = (rows, groups = GROUPS) => [
  PS.el("span", {class: "total"}, `${rows.length.toLocaleString("en-US")} ${rows.length === 1 ? "activity" : "activities"}`),
  ...PS.activityKeys(rows, groups),
];

// Orders activity rows by a table column (`key`: date, activity, person, or
// item) and `dir` ("asc" or "desc"). Ties go newest first.
PS.activityOrder = ({key, dir}) => {
  const {activity: A, kinds, docs} = PS.data;
  const text = {
    activity: i => KIND_LABELS[kinds[A.kind[i]]] || kinds[A.kind[i]],
    person: i => PS.personName(A.person[i]),
    item: i => (A.doc[i] < 0 ? "" : docs.title[A.doc[i]]),
  }[key];
  const sign = dir === "asc" ? 1 : -1;
  return (a, b) => sign * (text ? text(a).localeCompare(text(b)) : A.day[a] - A.day[b]) ||
    A.day[b] - A.day[a] || a - b;
};

// The sort after a click on column `key`: the same column flips; another starts
// newest first (Date) or A to Z.
PS.nextSort = (sort, key) => ({
  key, dir: sort.key === key ? (sort.dir === "asc" ? "desc" : "asc") : key === "date" ? "desc" : "asc",
});

// The Date / Activity / Item table for activity rows, already ordered by `sort`
// ({key, dir}) and cut to length. A click on a header calls `onSort(key)`;
// `people` adds a Person column, for lists that mix several people. `groups`
// colors the dots.
PS.activityTable = (rows, {sort, onSort, people = false, groups = GROUPS}) => {
  const {activity: A, kinds, docs} = PS.data;
  const header = (key, label) => {
    const on = sort.key === key;
    const order = key === "date" ? (sort.dir === "asc" ? "oldest first" : "newest first")
      : sort.dir === "asc" ? "A to Z" : "Z to A";
    const button = PS.el("button", {
      type: "button", class: "sort", "aria-label": on ? `${label}, ${order}. Click to reverse.` : `Sort by ${label}`,
    }, label, PS.el("span", {class: on ? (sort.dir === "asc" ? "chev up" : "chev") : "sort-none", "aria-hidden": "true"}));
    button.onclick = () => onSort(key);
    return PS.el("th", {scope: "col", "aria-sort": on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}, button);
  };
  const item = i => {
    const d = A.doc[i];
    return d < 0 ? "–" : PS.el("a", {href: PS.docUrl(d)}, docs.title[d]);
  };
  return PS.el("div", {class: "table-wrap"}, PS.el("table", {class: people ? "data activity with-person" : "data activity"},
    PS.el("thead", {}, PS.el("tr", {},
      header("date", "Date"), header("activity", "Activity"), people ? header("person", "Person") : null,
      header("item", "Item"))),
    PS.el("tbody", {}, rows.map(i => PS.el("tr", {},
      PS.el("td", {}, PS.dayToText(A.day[i])),
      PS.el("td", {}, dot(groupOf(kinds[A.kind[i]], groups)), KIND_LABELS[kinds[A.kind[i]]] || kinds[A.kind[i]]),
      people ? PS.el("td", {}, PS.personName(A.person[i])) : null,
      PS.el("td", {}, item(i)))))));
};

// The pane under a theme view: the activity behind a theme, or one of its heatmap
// cells, as a title with buttons, the total and keys, and a sortable table.
// Returns the nodes for `figure.details`. The sort and "Show all" live on `figure`;
// `extra` are buttons placed before Close, `rerender` redraws the view.
PS.themeActivity = (figure, {title, rows, extra = [], onClose, rerender}) => {
  if (!figure.sort) figure.sort = {key: "date", dir: "desc"};
  const mine = rows.slice().sort(PS.activityOrder(figure.sort));
  const limit = 50;
  const close = PS.el("button", {type: "button"}, "Close");
  close.onclick = onClose;
  const toggle = mine.length > limit ? PS.el("button", {type: "button"},
    figure.showAll ? "Show less" : `Show all ${mine.length.toLocaleString("en-US")}`) : null;
  if (toggle) {
    toggle.onclick = () => {
      figure.showAll = !figure.showAll;
      rerender();
    };
  }
  return [
    PS.el("div", {class: "details-head"}, PS.el("h3", {}, title), toggle, ...extra, close),
    PS.el("div", {class: "legend"}, PS.activitySummary(mine)),
    mine.length ? PS.activityTable(figure.showAll ? mine : mine.slice(0, limit), {
      sort: figure.sort,
      people: true,
      onSort: key => {
        figure.sort = PS.nextSort(figure.sort, key);
        rerender();
      },
    }) : PS.el("p", {class: "empty"}, "No activity matches the current filters."),
  ].filter(Boolean);
};

// `inPeriod`: the Overview's pane, limited to the open column. Otherwise the
// People tab's, whose rows ignore the left-out filter like its list does.
const pane = inPeriod => ({
  id: `${inPeriod ? "" : "people-"}activity`,
  title: "Activity",
  tab: inPeriod ? undefined : "people",
  order: inPeriod ? 20 : 30,
  noTable: true,
  projectKeys: [inPeriod ? "who" : "pwho"],
  render(figure, ctx) {
    const {data, state, set} = ctx;
    const rows = inPeriod ? ctx.rows : ctx.rowsExcept("people");
    const A = data.activity;
    const key = inPeriod ? "who" : "pwho";
    const person = PS.whoPick(state, key);
    const [kind, pickKey] = (state.pick || "").split(":");
    figure.root.hidden = person === undefined || (inPeriod && (kind !== state.period || !/^\d+$/.test(pickKey)));
    if (figure.root.hidden) return;

    const scheme = inPeriod ? PS.periodScheme(kind) : null;
    if (!figure.sort) figure.sort = {key: "date", dir: "desc"};
    const mine = rows
      .filter(i => A.person[i] === person && (!scheme || scheme.key(A.day[i]) === Number(pickKey)))
      .sort(PS.activityOrder(figure.sort));

    figure.root.querySelector(".head h3").replaceChildren(PS.personLink(person));
    const num = n => n.toLocaleString("en-US");
    figure.subtitle.textContent = scheme ? scheme.label(Number(pickKey)) : "";
    figure.subtitle.hidden = !scheme;
    figure.legend.hidden = false;
    figure.legend.replaceChildren(...PS.activitySummary(mine));

    const id = `${person}|${inPeriod ? state.pick : ""}`;
    if (figure.shownFor !== id) {
      figure.shownFor = id;
      figure.showAll = false;
    }
    if (!figure.close) {
      figure.toggle = PS.el("button", {type: "button"});
      figure.close = PS.el("button", {type: "button"}, "Close");
      figure.root.querySelector(".head").append(figure.toggle, figure.close);
    }
    figure.close.onclick = () => set(PS.whoToggle(state, person, key));
    figure.toggle.hidden = mine.length <= LIMIT;
    figure.toggle.textContent = figure.showAll ? "Show less" : `Show all ${num(mine.length)}`;
    figure.toggle.onclick = () => {
      figure.showAll = !figure.showAll;
      this.render(figure, ctx);
    };
    if (!mine.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No activity matches the current filters."));
      return;
    }
    figure.plot.replaceChildren(PS.activityTable(figure.showAll ? mine : mine.slice(0, LIMIT), {
      sort: figure.sort,
      onSort: key => {
        figure.sort = PS.nextSort(figure.sort, key);
        this.render(figure, ctx);
      },
    }));
  },
});

PS.registerView(pane(true));
PS.registerView(pane(false));
