// Control: the quarter thresholds for the core and regular segments. It
// filters no rows. Defaults come from [retention] in the project config.

// {core, regular, error}: the rules in effect. Invalid values fall back to
// the defaults, with `error` saying why.
PS.segmentRules = state => {
  const defaults = {core: PS.data.settings.core_quarters, regular: PS.data.settings.regular_quarters};
  const core = state.core === undefined ? defaults.core : Number(state.core);
  const regular = state.regular === undefined ? defaults.regular : Number(state.regular);
  const ok = Number.isInteger(core) && Number.isInteger(regular) && regular >= 1 && regular < core;
  return ok ? {core, regular, error: null}
    : {...defaults, error: `Regular must be at least 1 and below core; using ${defaults.regular} and ${defaults.core}.`};
};

PS.registerFilter({
  id: "segment-rules",
  control(box, state, set) {
    const defaults = PS.segmentRules({});
    const input = (key, label) => {
      const field = PS.el("input", {type: "number", min: 1, step: 1, class: "short", "aria-label": label});
      field.value = state[key] === undefined ? defaults[key] : state[key];
      field.onchange = () => {
        const value = field.value.trim();
        set({[key]: value === "" || Number(value) === defaults[key] ? undefined : value});
        sync();
      };
      return field;
    };
    const core = input("core", "Core: minimum active quarters");
    const regular = input("regular", "Regular: minimum active quarters");
    const error = PS.el("span", {class: "error", role: "status"});
    function sync() { error.textContent = PS.segmentRules(state).error || ""; }
    box.append(
      PS.el("span", {class: "label"}, "Segments"),
      "core ≥", core, "quarters, regular ≥", regular, error);
    sync();
  },
});
