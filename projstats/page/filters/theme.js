// Filter: one or more themes. Keeps activity on documents tagged with any of
// them, so every view narrows to those themes. Saved in the URL by theme
// name, joined with "|" (theme=Build system|Python).

// The selected themes' indexes, in the order picked.
PS.selectedThemes = state => {
  const names = (state.theme || "").split("|").filter(Boolean);
  return [...new Set(names.map(n => PS.data.themes.name.indexOf(n)).filter(t => t >= 0))];
};

// The state change that selects exactly these theme indexes.
PS.themePatch = themes => ({theme: themes.length ? themes.map(t => PS.data.themes.name[t]).join("|") : undefined});

PS.registerFilter({
  id: "theme",
  secondary: true,
  control(box, state, set) {
    const T = PS.data.themes;
    // Still listed when there is nothing to pick, so it is clear the filter exists.
    if (!T.name.length) {
      const why = PS.data.features.themes ? "No themes yet; run projstats tag."
        : "Themes are off for this project ([themes] enabled = false in its config).";
      box.append(PS.el("span", {class: "label"}, "Theme"),
        PS.el("span", {class: "has-tip", title: why},
          PS.el("select", {"aria-label": "Theme", disabled: true}, PS.el("option", {}, "No data available"))));
      return;
    }
    const docsPer = new Array(T.name.length).fill(0);
    for (const t of T.theme) docsPer[t] += 1;
    const order = T.name.map((_, t) => t).sort((a, b) => T.name[a].localeCompare(T.name[b]));

    // A checklist in a popover: the check column stays at the left, so names
    // line up whether or not they are picked, and the list stays open while
    // several are ticked.
    this.checks = new Map();
    const list = PS.el("div", {class: "menu-list", role: "group", "aria-label": "Themes", hidden: true});
    for (const t of order) {
      const input = PS.el("input", {type: "checkbox"});
      input.onchange = () => {
        const picked = PS.selectedThemes(PS.state);
        set(PS.themePatch(input.checked ? [...picked, t] : picked.filter(u => u !== t)));
      };
      this.checks.set(t, input);
      list.append(PS.el("label", {class: "option"}, input,
        PS.el("span", {}, T.name[t]), PS.el("span", {class: "count"}, docsPer[t])));
    }
    this.buttonText = PS.el("span", {});
    const button = PS.el("button", {
      type: "button", class: "menu-button", "aria-expanded": "false", "aria-label": "Theme",
    }, this.buttonText, PS.el("span", {class: "chev", "aria-hidden": "true"}));
    const menu = PS.el("span", {class: "menu"}, button, list);
    const toggle = open => {
      list.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    };
    button.onclick = () => toggle(list.hidden);
    document.addEventListener("click", event => { if (!menu.contains(event.target)) toggle(false); });
    menu.addEventListener("keydown", event => {
      if (event.key !== "Escape" || list.hidden) return;
      toggle(false);
      button.focus();
    });
    this.sync(state);

    // Tagging may cover only recent documents; say from when.
    const days = T.tagged.map(d => PS.data.docs.day[d]);
    const note = days.length
      ? PS.el("span", {class: "note"}, `tags from ${PS.dayToText(Math.min(...days))}`) : null;
    box.append(PS.el("span", {class: "label"}, "Theme"), menu, note);
  },
  sync(state) {
    if (!this.checks) return;
    const picked = PS.selectedThemes(state);
    for (const [t, input] of this.checks) input.checked = picked.includes(t);
    this.buttonText.textContent = !picked.length ? "All themes"
      : picked.length === 1 ? PS.data.themes.name[picked[0]] : `${picked.length} selected`;
  },
  chips(state) {
    const picked = PS.selectedThemes(state);
    return picked.map(t => ({
      text: `Theme: ${PS.data.themes.name[t]}`,
      clear: PS.themePatch(picked.filter(u => u !== t)),
    }));
  },
  predicate(state) {
    const picked = new Set(PS.selectedThemes(state));
    if (!picked.size) return null;
    const docs = new Uint8Array(PS.data.docs.day.length);
    PS.data.themes.doc.forEach((d, k) => { if (picked.has(PS.data.themes.theme[k])) docs[d] = 1; });
    const doc = PS.data.activity.doc;
    return i => doc[i] >= 0 && docs[doc[i]] === 1;
  },
});
