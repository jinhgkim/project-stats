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
const groupOf = kind => GROUPS.find(g => g.kinds.includes(kind));
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

// `inPeriod`: the Overview's pane, limited to the open column. Otherwise the
// People tab's, whose rows ignore the left-out filter like its list does.
const pane = inPeriod => ({
  id: `${inPeriod ? "" : "people-"}activity`,
  title: "Activity",
  tab: inPeriod ? undefined : "people",
  order: inPeriod ? 20 : 30,
  noTable: true,
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
    const mine = rows
      .filter(i => A.person[i] === person && (!scheme || scheme.key(A.day[i]) === Number(pickKey)))
      .sort((a, b) => (figure.oldestFirst ? A.day[a] - A.day[b] : A.day[b] - A.day[a]));

    figure.root.querySelector(".head h3").replaceChildren(PS.personLink(person));
    const counts = new Map();
    for (const i of mine) counts.set(A.kind[i], (counts.get(A.kind[i]) || 0) + 1);
    const num = n => n.toLocaleString("en-US");
    const groups = GROUPS.map(g => {
      const inGroup = [...counts].filter(([k]) => g.kinds.includes(data.kinds[k])).sort((a, b) => b[1] - a[1]);
      if (!inGroup.length) return null;
      const detail = inGroup.map(([k, n]) => `${num(n)} ${kindName(data.kinds[k], n)}`).join(", ");
      return PS.el("span", {class: "key"}, dot(g),
        `${g.name} ${num(inGroup.reduce((sum, [, n]) => sum + n, 0))} (${detail})`);
    });
    figure.subtitle.textContent = `${scheme ? `${scheme.label(Number(pickKey))} · ` : ""}` +
      `${num(mine.length)} ${mine.length === 1 ? "activity" : "activities"}`;
    figure.legend.hidden = groups.every(g => !g);
    figure.legend.replaceChildren(...groups.filter(Boolean));

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
    const sortButton = PS.el("button", {
      type: "button", class: "sort",
      "aria-label": `Date, ${figure.oldestFirst ? "oldest" : "newest"} first. Click to reverse.`,
    }, "Date", PS.el("span", {class: figure.oldestFirst ? "chev up" : "chev", "aria-hidden": "true"}));
    sortButton.onclick = () => {
      figure.oldestFirst = !figure.oldestFirst;
      this.render(figure, ctx);
    };
    const item = i => {
      const d = A.doc[i];
      return d < 0 ? "–" : PS.el("a", {href: PS.docUrl(d)}, data.docs.title[d]);
    };
    figure.plot.replaceChildren(
      PS.el("div", {class: "table-wrap"}, PS.el("table", {class: "data activity"},
        PS.el("thead", {}, PS.el("tr", {},
          PS.el("th", {scope: "col", "aria-sort": figure.oldestFirst ? "ascending" : "descending"}, sortButton),
          PS.el("th", {scope: "col"}, "Activity"), PS.el("th", {scope: "col"}, "Item"))),
        PS.el("tbody", {}, (figure.showAll ? mine : mine.slice(0, LIMIT)).map(i => PS.el("tr", {},
          PS.el("td", {}, PS.dayToText(A.day[i])),
          PS.el("td", {}, dot(groupOf(data.kinds[A.kind[i]])),
            KIND_LABELS[data.kinds[A.kind[i]]] || data.kinds[A.kind[i]]),
          PS.el("td", {}, item(i))))))),
    );
  },
});

PS.registerView(pane(true));
PS.registerView(pane(false));
