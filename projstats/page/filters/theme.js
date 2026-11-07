// Filter: one theme. Keeps activity on documents tagged with it, so every
// view narrows to that theme. Saved in the URL by theme name.

// The selected theme's index, or null.
PS.selectedTheme = state => {
  if (!state.theme) return null;
  const t = PS.data.themes.name.indexOf(state.theme);
  return t < 0 ? null : t;
};

PS.registerFilter({
  id: "theme",
  control(box, state, set) {
    const T = PS.data.themes;
    if (!T.name.length) return;
    const docsPer = new Array(T.name.length).fill(0);
    for (const t of T.theme) docsPer[t] += 1;
    const order = T.name.map((_, t) => t).sort((a, b) => T.name[a].localeCompare(T.name[b]));
    const select = PS.el("select", {"aria-label": "Theme"},
      PS.el("option", {value: ""}, "All themes"),
      ...order.map(t => PS.el("option", {value: T.name[t]}, `${T.name[t]} (${docsPer[t]})`)));
    this.select = select;
    this.sync(state);
    select.onchange = () => set({theme: select.value || undefined});
    // Tagging may cover only recent documents; say from when.
    const days = T.tagged.map(d => PS.data.docs.day[d]);
    const note = days.length
      ? PS.el("span", {class: "note"}, `tags from ${PS.dayToText(Math.min(...days))}`) : null;
    box.append(PS.el("span", {class: "label"}, "Theme"), select, note);
  },
  sync(state) {
    if (this.select) this.select.value = PS.selectedTheme(state) === null ? "" : state.theme;
  },
  predicate(state) {
    const t = PS.selectedTheme(state);
    if (t === null) return null;
    const docs = new Uint8Array(PS.data.docs.day.length);
    PS.data.themes.doc.forEach((d, k) => { if (PS.data.themes.theme[k] === t) docs[d] = 1; });
    const doc = PS.data.activity.doc;
    return i => doc[i] >= 0 && docs[doc[i]] === 1;
  },
});
