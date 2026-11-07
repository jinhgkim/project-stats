// View: the activity of up to two people in the Overview's open column, shown
// under the contributors list, one pane each (side by side when there are two).
// Choosing a name there toggles it in `who` (person indexes, comma separated);
// the period is that list's `pick`. A pane is hidden until its person and the
// column are set.

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
const KIND_PLURALS = {commit: "commits", pr: "PRs opened", review: "reviews", issue: "issues opened", comment: "comments"};

const LIMIT = 50;
const PANES = 2;

// The people chosen, oldest choice first.
PS.whoList = state => [...new Set((state.who || "").split(",").filter(s => /^\d+$/.test(s)).map(Number))]
  .filter(i => i < PS.data.people.name.length).slice(0, PANES);

// The state change that picks a person, or drops them when already picked. A
// pick beyond the limit replaces the oldest one.
PS.whoToggle = (state, person) => {
  const now = PS.whoList(state);
  const next = now.includes(person) ? now.filter(p => p !== person) : [...now, person].slice(-PANES);
  return {who: next.length ? next.join(",") : undefined};
};

const pane = slot => ({
  id: slot ? `activity-${slot + 1}` : "activity",
  title: "Activity",
  order: 20 + slot,
  noTable: true,
  render(figure, ctx) {
    const {data, rows, state, set} = ctx;
    const A = data.activity;
    const people = PS.whoList(state);
    const person = people[slot];
    const [kind, key] = (state.pick || "").split(":");
    figure.root.classList.toggle("half", people.length > 1);
    figure.root.hidden = person === undefined || kind !== state.period || !/^\d+$/.test(key);
    if (figure.root.hidden) return;

    const scheme = PS.periodScheme(kind);
    const mine = rows
      .filter(i => A.person[i] === person && scheme.key(A.day[i]) === Number(key))
      .sort((a, b) => (figure.oldestFirst ? A.day[a] - A.day[b] : A.day[b] - A.day[a]));

    figure.root.querySelector(".head h3").replaceChildren(PS.personLink(person));
    const counts = new Map();
    for (const i of mine) counts.set(A.kind[i], (counts.get(A.kind[i]) || 0) + 1);
    const num = n => n.toLocaleString("en-US");
    const groups = GROUPS.map(g => {
      const inGroup = [...counts].filter(([k]) => g.kinds.includes(data.kinds[k])).sort((a, b) => b[1] - a[1]);
      if (!inGroup.length) return null;
      const detail = inGroup.map(([k, n]) => `${num(n)} ${KIND_PLURALS[data.kinds[k]] || data.kinds[k]}`).join(", ");
      return PS.el("span", {class: "key"}, dot(g),
        `${g.name} ${num(inGroup.reduce((sum, [, n]) => sum + n, 0))} (${detail})`);
    });
    figure.subtitle.textContent =
      `${scheme.label(Number(key))} · ${num(mine.length)} ${mine.length === 1 ? "activity" : "activities"}`;
    figure.legend.hidden = groups.every(g => !g);
    figure.legend.replaceChildren(...groups.filter(Boolean));

    const id = `${person}|${state.pick}`;
    if (figure.shownFor !== id) {
      figure.shownFor = id;
      figure.showAll = false;
    }
    if (!figure.close) {
      figure.toggle = PS.el("button", {type: "button"});
      figure.close = PS.el("button", {type: "button"}, "Close");
      figure.root.querySelector(".head").append(figure.toggle, figure.close);
    }
    figure.close.onclick = () => set(PS.whoToggle(state, person));
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

for (let slot = 0; slot < PANES; slot++) PS.registerView(pane(slot));
