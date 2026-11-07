// Setting: the activity shares for the core and regular segments. It filters
// no rows, so it sits in the Segments view. Defaults come from [retention]
// in the project config; the URL keeps percents (core=80&regular=95).

// {core, regular, error}: the shares in effect, as fractions. Invalid values
// fall back to the defaults, with `error` saying why.
PS.segmentRules = state => {
  const defaults = {core: PS.data.settings.core_share, regular: PS.data.settings.regular_share};
  const core = state.core === undefined ? defaults.core : Number(state.core) / 100;
  const regular = state.regular === undefined ? defaults.regular : Number(state.regular) / 100;
  const ok = core > 0 && core < regular && regular <= 1;
  const pct = v => Math.round(v * 100);
  return ok ? {core, regular, error: null}
    : {...defaults, error: `Core must be above 0% and below regular, and regular at most 100%; ` +
       `using ${pct(defaults.core)}% and ${pct(defaults.regular)}%.`};
};

PS.registerFilter({
  id: "segment-rules",
  target: "segments",
  control(box, state, set) {
    const defaults = PS.segmentRules({});
    const input = (key, label) => {
      const field = PS.el("input", {type: "number", min: 1, max: 100, step: 1, class: "short", "aria-label": label});
      field.value = state[key] === undefined ? Math.round(defaults[key] * 100) : state[key];
      field.onchange = () => {
        const v = field.value.trim();
        set({[key]: v === "" || Number(v) === Math.round(defaults[key] * 100) ? undefined : v});
        sync();
      };
      return field;
    };
    const core = input("core", "Core: share of all activity, in percent");
    const regular = input("regular", "Regular: share of all activity, in percent");
    const error = PS.el("span", {class: "error", role: "status"});
    function sync() { error.textContent = PS.segmentRules(state).error || ""; }
    box.append(
      PS.el("span", {class: "label"}, "Cutoffs"),
      "core: top", core, "% of activity, regular: up to", regular, "%", error);
    sync();
  },
});
