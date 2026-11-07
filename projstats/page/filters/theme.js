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
  feature: "themes",
  secondary: true,
  control(box, state, set) {
    const T = PS.data.themes;
    if (!T.name.length) return;
    const docsPer = new Array(T.name.length).fill(0);
    for (const t of T.theme) docsPer[t] += 1;
    this.order = T.name.map((_, t) => t).sort((a, b) => T.name[a].localeCompare(T.name[b]));
    this.docsPer = docsPer;
    this.select = PS.el("select", {"aria-label": "Add a theme"});
    this.sync(state);
    this.select.onchange = () => {
      if (this.select.value === "") return;
      const t = Number(this.select.value);
      const picked = PS.selectedThemes(PS.state);
      set(PS.themePatch(picked.includes(t) ? picked.filter(u => u !== t) : [...picked, t]));
    };
    // Tagging may cover only recent documents; say from when.
    const days = T.tagged.map(d => PS.data.docs.day[d]);
    const note = days.length
      ? PS.el("span", {class: "note"}, `tags from ${PS.dayToText(Math.min(...days))}`) : null;
    box.append(PS.el("span", {class: "label"}, "Theme"), this.select, note);
  },
  // Every theme is listed, picked ones with a check; choosing one toggles it.
  // The first option is the closed select's text and never changes the filter.
  sync(state) {
    if (!this.select) return;
    const picked = PS.selectedThemes(state);
    const T = PS.data.themes;
    this.select.replaceChildren(
      PS.el("option", {value: ""}, picked.length ? `${picked.length} selected` : "All themes"),
      ...this.order.map(t => PS.el("option", {value: t},
        `${picked.includes(t) ? "✓ " : ""}${T.name[t]} (${this.docsPer[t]})`)));
    this.select.value = "";
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
