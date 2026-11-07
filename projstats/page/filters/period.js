// Setting: the period the contributors chart and the timeline group by. It
// filters no rows, but two tabs use it, so it sits in the top bar.

PS.registerFilter({
  id: "period",
  init(state) {
    const valid = ["month", "quarter", "year", "release"];
    if (!valid.includes(state.period)) state.period = "quarter";
    if (state.period === "release" && !PS.data.releases.day.length) state.period = "quarter";
  },
  control(box, state, set) {
    const options = [["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
    if (PS.data.releases.day.length) options.push(["release", "Release cycle"]);
    const select = PS.el("select", {"aria-label": "Group by"},
      ...options.map(([value, name]) => PS.el("option", {value}, name)));
    select.value = state.period;
    select.onchange = () => set({period: select.value});
    this.select = select;
    box.append(PS.el("span", {class: "label"}, "Group by"), select);
  },
  sync(state) { if (this.select) this.select.value = state.period; },
});
