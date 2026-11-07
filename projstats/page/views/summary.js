// View: headline numbers at the top of the page, from the same filtered rows
// as the views below. Each tile opens the list of those people (in Segments).

PS.registerView({
  id: "summary",
  title: "Summary",
  tab: "overview",
  bare: true,
  order: 0,
  render(figure, {data, rows, state}) {
    const gap = data.settings.return_gap_days;
    const rules = PS.segmentRules(state);
    const {stats, dataEnd} = PS.metrics.personStats(rows, data, rules, gap);
    const tile = (value, what, more, target) => {
      const button = PS.el("button", {type: "button", class: "tile"},
        PS.el("span", {class: "value"}, value),
        PS.el("span", {class: "what"}, what),
        more ? PS.el("span", {class: "more"}, more) : null);
      button.onclick = () => PS.jumpTo(...target);
      return button;
    };
    if (!stats.length) {
      figure.plot.replaceChildren(PS.el("p", {class: "empty"}, "No activity matches the filters."));
      return;
    }
    const fmt = n => n.toLocaleString("en-US");
    const active = stats.filter(s => s.current).length;
    const fresh = stats.filter(s => dataEnd - s.first < gap).length;
    const core = stats.filter(s => s.segment === "core");
    const total = stats.reduce((sum, s) => sum + s.activity, 0);
    const coreShare = total ? core.reduce((sum, s) => sum + s.activity, 0) / total : 0;
    const tiles = [
      tile(fmt(active), `active in the last ${gap} days`, `of ${fmt(stats.length)} people in the data shown`,
        ["details-segments", {list: "active"}]),
      tile(fmt(fresh), `new in the last ${gap} days`, "first activity in that time",
        ["details-segments", {list: "new"}]),
      tile(fmt(core.length), `people do ${Math.round(coreShare * 100)}% of the activity`,
        "the core: see who they are", ["details-segments", {list: "core"}]),
    ];

    figure.plot.replaceChildren(PS.el("div", {class: "tiles"}, tiles));
  },
});
