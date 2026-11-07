// Filter: a checkbox per person listed in [people] leave_out_option, so one
// very active person can be left out of every count. The URL lists the
// logins left out (without=lgritz).

const optionalPeople = () => PS.data.project.leave_out_option || [];

// Indexes of the optional people currently left out.
PS.leftOut = state => {
  const logins = new Set((state.without || "").split(",").filter(Boolean));
  return optionalPeople().filter(p => logins.has(PS.data.people.login[p]));
};

PS.registerFilter({
  id: "people",
  control(box, state, set) {
    const people = optionalPeople();
    if (!people.length) return;
    this.boxes = people.map(p => {
      const input = PS.el("input", {type: "checkbox"});
      input.onchange = () => {
        const out = people.filter((_, i) => !this.boxes[i].checked).map(q => PS.data.people.login[q]);
        set({without: out.length ? out.join(",") : undefined});
      };
      box.append(PS.el("label", {class: "check"}, input, `Include ${PS.personName(p)}`));
      return input;
    });
    this.sync(state);
  },
  sync(state) {
    if (!this.boxes) return;
    const out = new Set(PS.leftOut(state));
    optionalPeople().forEach((p, i) => { this.boxes[i].checked = !out.has(p); });
  },
  predicate(state) {
    const out = new Set(PS.leftOut(state));
    if (!out.size) return null;
    const person = PS.data.activity.person;
    return i => !out.has(person[i]);
  },
});
