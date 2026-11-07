// Control: the period every time-based view groups by. It filters no rows.

PS.registerFilter({
  id: "period",
  init(state) {
    const valid = ["month", "quarter", "year", "release"];
    if (!valid.includes(state.period)) state.period = "year";
    if (state.period === "release" && !PS.data.releases.day.length) state.period = "year";
  },
  control(box, state, set) {
    const options = [["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
    if (PS.data.releases.day.length) options.push(["release", "Release cycle"]);
    const select = PS.el("select", {"aria-label": "Group by"},
      ...options.map(([value, name]) => PS.el("option", {value}, name)));
    select.value = state.period;
    select.onchange = () => set({period: select.value});
    box.append(PS.el("span", {class: "label"}, "Group by"), select);
  },
});
