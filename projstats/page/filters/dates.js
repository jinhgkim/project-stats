// Filter: date range (inclusive), with presets. Dates are UTC days.

PS.registerFilter({
  id: "dates",
  control(box, state, set) {
    const end = PS.data.project.data_end;
    const github = PS.data.sources.pr;
    const endText = end === null ? null : PS.dayToText(end);
    const fiveYears = endText && `${Number(endText.slice(0, 4)) - 5}${endText.slice(4)}`;
    const presets = [
      {id: "all", name: "All time", from: undefined, to: undefined},
      github !== undefined && {
        id: "github", name: `Since GitHub PRs (${PS.dayToText(github).slice(0, 7)})`,
        from: PS.dayToText(github), to: undefined,
      },
      fiveYears && {id: "5y", name: "Last 5 years", from: fiveYears, to: undefined},
    ].filter(Boolean);

    const select = PS.el("select", {"aria-label": "Date range"},
      ...presets.map(p => PS.el("option", {value: p.id}, p.name)),
      PS.el("option", {value: "custom"}, "Custom"));
    const from = PS.el("input", {type: "date", "aria-label": "From"});
    const to = PS.el("input", {type: "date", "aria-label": "To"});

    function sync() {
      from.value = state.from || "";
      to.value = state.to || "";
      const match = presets.find(p => (p.from || "") === (state.from || "") && !state.to);
      select.value = match ? match.id : "custom";
    }
    select.onchange = () => {
      const preset = presets.find(p => p.id === select.value);
      if (preset) set({from: preset.from, to: preset.to});
      sync();
    };
    from.onchange = () => { set({from: from.value || undefined}); sync(); };
    to.onchange = () => { set({to: to.value || undefined}); sync(); };

    box.append(PS.el("span", {class: "label"}, "Dates"), select, from, PS.el("span", {}, "to"), to);
    sync();
    this.syncControl = sync;
  },
  sync() { if (this.syncControl) this.syncControl(); },
  predicate(state) {
    if (!state.from && !state.to) return null;
    const lo = state.from ? PS.dateToDay(state.from) : -Infinity;
    const hi = state.to ? PS.dateToDay(state.to) : Infinity;
    const day = PS.data.activity.day;
    return i => day[i] >= lo && day[i] <= hi;
  },
});
