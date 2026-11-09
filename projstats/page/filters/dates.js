// Filter: date range (inclusive), with presets. Dates are UTC days. An empty
// start or end means open-ended, so the fields show the first day of data and
// today's date.

PS.registerFilter({
  id: "dates",
  keys: ["from", "to"],
  control(box, state, set) {
    const end = PS.data.project.data_end;
    const github = PS.data.sources.pr;
    const endText = end === null ? null : PS.dayToText(end);
    const yearsBack = n => endText && `${Number(endText.slice(0, 4)) - n}${endText.slice(4)}`;
    // n whole months before the end, with the day cut to the month's length.
    const monthsBack = n => {
      if (!endText) return null;
      const [y, m, d] = endText.split("-").map(Number);
      const lastDay = new Date(Date.UTC(y, m - 1 - n + 1, 0)).getUTCDate();
      return new Date(Date.UTC(y, m - 1 - n, Math.min(d, lastDay))).toISOString().slice(0, 10);
    };
    const now = new Date();
    const today = [now.getFullYear(), now.getMonth() + 1, now.getDate()]
      .map((n, i) => String(n).padStart(i ? 2 : 4, "0")).join("-");
    const days = PS.data.activity.day;
    const first = days.length ? PS.dayToText(days.reduce((a, b) => (b < a ? b : a))) : "";
    const presets = [
      {id: "all", name: "All time", from: undefined, to: undefined},
      github !== undefined && {
        id: "github", name: "Since GitHub PRs",
        from: PS.dayToText(github), to: undefined,
      },
      endText && {id: "3y", name: "Last 3 years", from: yearsBack(3), to: undefined},
      endText && {id: "1y", name: "Last 1 year", from: yearsBack(1), to: undefined},
      endText && {id: "3m", name: "Last 3 months", from: monthsBack(3), to: undefined},
    ].filter(Boolean);

    const select = PS.el("select", {"aria-label": "Date range"},
      ...presets.map(p => PS.el("option", {value: p.id}, p.name)),
      // Shown only while typed dates match no preset; never offered as a choice.
      PS.el("option", {value: "custom", hidden: true, disabled: true}, "Custom"));
    const from = PS.el("input", {type: "date", "aria-label": "From", min: first, max: today});
    const to = PS.el("input", {type: "date", "aria-label": "To", min: first, max: today});

    function sync() {
      from.value = state.from || first;
      to.value = state.to || today;
      const match = presets.find(p => (p.from || "") === (state.from || "") && !state.to);
      select.value = match ? match.id : "custom";
    }
    select.onchange = () => {
      const preset = presets.find(p => p.id === select.value);
      if (preset) set({from: preset.from, to: preset.to});
      sync();
    };
    from.onchange = () => { set({from: from.value && from.value !== first ? from.value : undefined}); sync(); };
    to.onchange = () => { set({to: to.value && to.value !== today ? to.value : undefined}); sync(); };

    box.append(PS.el("span", {class: "label"}, "Dates"), select, from, PS.el("span", {}, "to"), to);
    sync();
    this.syncControl = sync;
    this.presets = presets;
  },
  sync() { if (this.syncControl) this.syncControl(); },
  chips(state) {
    if (!state.from && !state.to) return [];
    const match = this.presets.find(p => (p.from || "") === (state.from || "") && !state.to);
    const text = match ? match.name
      : state.from && state.to ? `${state.from} to ${state.to}`
      : state.from ? `From ${state.from}` : `Until ${state.to}`;
    return [{text, clear: {from: undefined, to: undefined}}];
  },
  predicate(state) {
    if (!state.from && !state.to) return null;
    const lo = state.from ? PS.dateToDay(state.from) : -Infinity;
    const hi = state.to ? PS.dateToDay(state.to) : Infinity;
    const day = PS.data.activity.day;
    return i => day[i] >= lo && day[i] <= hi;
  },
});
