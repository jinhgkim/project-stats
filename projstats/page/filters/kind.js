// Filter: which activity kinds count. At least one stays selected.

PS.registerFilter({
  id: "kind",
  control(box, state, set) {
    const names = {commit: "Commits", pr: "PRs opened", review: "Reviews",
                   issue: "Issues opened", comment: "Comments"};
    const kinds = PS.data.kinds;
    box.append(PS.el("span", {class: "label"}, "Activity"));
    const buttons = kinds.map(kind => {
      const name = names[kind] || kind;
      const button = PS.el("button", {type: "button", "data-label": name}, name);
      button.onclick = () => {
        const on = new Set(PS.selectedKinds());
        if (on.has(kind)) {
          if (on.size === 1) return;
          on.delete(kind);
        } else {
          on.add(kind);
        }
        const list = kinds.filter(k => on.has(k));
        set({kinds: list.length === kinds.length ? undefined : list.join(",")});
        sync();
      };
      return button;
    });
    function sync() {
      const on = new Set(PS.selectedKinds());
      buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(on.has(kinds[i]))));
    }
    box.append(...buttons);
    sync();
  },
  predicate(state) {
    const on = new Set(PS.selectedKinds());
    if (on.size === PS.data.kinds.length) return null;
    const allowed = PS.data.kinds.map(k => on.has(k));
    const kind = PS.data.activity.kind;
    return i => allowed[kind[i]];
  },
});
