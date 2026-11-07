// Filter: which activity counts, as one choice: All, Code, or Discussion.
// The hash keeps the individual kinds (#kinds=commit,pr). Older links with
// other combinations are widened to the whole group (or to All) on load.

const KIND_GROUPS = {
  code: ["commit", "pr"],
  discussion: ["review", "issue", "comment"],
};

PS.registerFilter({
  id: "kind",
  init(state) {
    if (!state.kinds) return;
    const on = state.kinds.split(",").filter(k => PS.data.kinds.includes(k));
    const within = group => on.length && on.every(k => KIND_GROUPS[group].includes(k));
    const pick = within("code") ? "code" : within("discussion") ? "discussion" : null;
    state.kinds = pick ? KIND_GROUPS[pick].filter(k => PS.data.kinds.includes(k)).join(",") : undefined;
  },
  control(box, state, set) {
    const has = k => PS.data.kinds.includes(k);
    const code = KIND_GROUPS.code.filter(has);
    const discussion = KIND_GROUPS.discussion.filter(has);
    if (!code.length || !discussion.length) return;
    const options = [
      {name: "All", title: "Commits, PRs opened, reviews, issues opened, and comments", kinds: undefined},
      {name: "Code", title: "Commits and PRs opened", kinds: code},
      {name: "Discussion", title: "Reviews, issues opened, and comments", kinds: discussion},
    ];
    const current = () => {
      const on = PS.selectedKinds();
      if (on.every(k => code.includes(k))) return 1;
      if (on.every(k => discussion.includes(k))) return 2;
      return 0;
    };
    const choose = i => {
      if (i === current()) return;
      set({kinds: options[i].kinds && options[i].kinds.join(",")});
      sync();
    };
    box.append(PS.el("span", {class: "label", id: "kind-label"}, "Activity"));
    const group = PS.el("span", {class: "choice", role: "radiogroup", "aria-labelledby": "kind-label"});
    const buttons = options.map((o, i) => {
      const button = PS.el("button", {type: "button", role: "radio", title: o.title, "data-label": o.name}, o.name);
      button.onclick = () => choose(i);
      button.onfocus = () => choose(i);
      return button;
    });
    function sync() {
      const now = current();
      buttons.forEach((b, i) => {
        b.setAttribute("aria-checked", String(i === now));
        b.setAttribute("tabindex", i === now ? 0 : -1);
      });
    }
    group.append(...buttons);
    box.append(group);
    PS.rovingFocus(buttons, current(), "ArrowLeft", "ArrowRight");
    sync();
    this.syncControl = sync;
    this.pick = () => (current() ? options[current()].name : null);
  },
  sync() { if (this.syncControl) this.syncControl(); },
  chips() {
    const name = this.pick && this.pick();
    return name ? [{text: `Activity: ${name}`, clear: {kinds: undefined}}] : [];
  },
  predicate(state) {
    const on = new Set(PS.selectedKinds());
    if (on.size === PS.data.kinds.length) return null;
    const allowed = PS.data.kinds.map(k => on.has(k));
    const kind = PS.data.activity.kind;
    return i => allowed[kind[i]];
  },
});
