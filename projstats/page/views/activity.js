// View: the activity of a person, one pane each. Choosing a name toggles it
// in the URL as person indexes. The Overview's panes (`who`, up to two, side
// by side) sit under the contributors list and show the open column (`pick`),
// so they stay hidden until it is set. The People tab's pane (`pwho`, one)
// sits under the people list and shows everything the filters leave.

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
const MAX = {who: 2, pwho: 1};

// The people chosen under URL key `who` or `pwho`, oldest choice first.
PS.whoList = (state, key = "who") => [...new Set((state[key] || "").split(",").filter(s => /^\d+$/.test(s)).map(Number))]
  .filter(i => i < PS.data.people.name.length).slice(0, MAX[key]);

// The state change that picks a person, or drops them when already picked. A
// pick beyond the limit replaces the oldest one.
PS.whoToggle = (state, person, key = "who") => {
  const now = PS.whoList(state, key);
  const next = now.includes(person) ? now.filter(p => p !== person) : [...now, person].slice(-MAX[key]);
  return {[key]: next.length ? next.join(",") : undefined};
};

// A name that opens that person's pane (`prefix` "people-" for the People tab's).
PS.personButton = (person, state, prefix = "") => {
  const key = prefix ? "pwho" : "who";
  return PS.el("button", {
    type: "button", class: "link-button", "aria-expanded": String(PS.whoList(state, key).includes(person)),
    onclick: () => {
      const patch = PS.whoToggle(state, person, key);
      const slot = PS.whoList(patch, key).indexOf(person);
      if (slot < 0) PS.set(patch);
      else PS.jumpTo(`view-${prefix}activity${slot ? `-${slot + 1}` : ""}`, patch);
    },
  }, PS.personName(person));
};

// `inPeriod`: the Overview's pane, limited to the open column. Otherwise the
// People tab's, whose rows ignore the left-out filter like its list does.
const pane = (slot, inPeriod) => ({
  id: `${inPeriod ? "" : "people-"}activity${slot ? `-${slot + 1}` : ""}`,
  title: "Activity",
  tab: inPeriod ? undefined : "people",
  order: (inPeriod ? 20 : 30) + slot,
  noTable: true,
  render(figure, ctx) {
    const {data, state, set} = ctx;
    const rows = inPeriod ? ctx.rows : ctx.rowsExcept("people");
    const A = data.activity;
    const key = inPeriod ? "who" : "pwho";
    const people = PS.whoList(state, key);
    const person = people[slot];
    const [kind, pickKey] = (state.pick || "").split(":");
    figure.root.classList.toggle("half", people.length > 1);
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

for (let slot = 0; slot < MAX.who; slot++) PS.registerView(pane(slot, true));
PS.registerView(pane(0, false));
