// Retention math in the browser, mirroring projstats/retention.py at day
// precision. #check compares these results with Python's reference numbers.

PS.metrics = (() => {
  // rows: activity indexes; scheme: PS.periodScheme(...); gapDays: return gap.
  // Returns one row per period from the first to the last with activity,
  // empty periods included. Mirrors retention.period_counts().
  function periodCounts(rows, data, scheme, gapDays) {
    if (!rows.length) return [];
    const A = data.activity;
    const days = new Map();  // person -> days
    let minKey = Infinity, maxKey = -Infinity, dataEnd = -Infinity;
    for (const i of rows) {
      const day = A.day[i];
      const person = A.person[i];
      if (!days.has(person)) days.set(person, []);
      days.get(person).push(day);
      const key = scheme.key(day);
      if (key < minKey) minKey = key;
      if (key > maxKey) maxKey = key;
      if (day > dataEnd) dataEnd = day;
    }
    const out = new Map();
    for (let key = minKey; key <= maxKey; key++) {
      const [start, end] = scheme.bounds(key);
      out.set(key, {
        key, label: scheme.label(key), short: scheme.short(key), start, end,
        active: 0, new: 0, returning: 0, continuing: 0, lastSeen: null,
        activity: 0, partial: key === maxKey, people: [],
      });
    }
    const lastSeen = new Map();
    for (const [person, list] of days) {
      list.sort((a, b) => a - b);
      let prev = null;
      let i = 0;
      while (i < list.length) {
        const key = scheme.key(list[i]);
        let j = i;
        while (j + 1 < list.length && scheme.key(list[j + 1]) === key) j++;
        const row = out.get(key);
        row.active += 1;
        row.activity += j - i + 1;
        const kind = prev === null ? "new" : list[i] - prev >= gapDays ? "returning" : "continuing";
        row[kind] += 1;
        row.people.push({person, kind, activity: j - i + 1});
        prev = list[j];
        i = j + 1;
      }
      const lastKey = scheme.key(list[list.length - 1]);
      lastSeen.set(lastKey, (lastSeen.get(lastKey) || 0) + 1);
    }
    for (const row of out.values()) {
      if (row.end !== null && dataEnd - row.end >= gapDays) {
        row.lastSeen = lastSeen.get(row.key) || 0;
      }
    }
    return [...out.values()];
  }

  // rules: {core, regular} shares of all activity (e.g. 0.8, 0.95). Returns a
  // function from a person's activity count to their segment. Mirrors
  // retention.segments(): one-time is exactly one activity; ranked by
  // activity, core is the top group that reaches the core share and regular
  // the next group up to the regular share, ties at a cutoff included.
  function segmenter(counts, rules) {
    const total = counts.reduce((sum, n) => sum + n, 0);
    const ranked = [...counts].sort((a, b) => b - a);
    const cutoff = share => {
      let run = 0;
      for (const n of ranked) {
        run += n;
        if (run >= share * total) return n;
      }
      return 0;
    };
    const coreMin = cutoff(rules.core), regularMin = cutoff(rules.regular);
    return n => (n === 1 ? "one-time" : n >= coreMin ? "core" : n >= regularMin ? "regular" : "casual");
  }

  // Cadence per person over `rows`. Mirrors retention.person_stats():
  // segments come from each person's share of the activity in `segmentRows`
  // (default: `rows`), and "current" means active within gapDays of the last
  // day in `rows`. Passing the rows with everyone counted keeps the same
  // people in each segment when someone is left out of `rows`.
  // Returns {stats, dataEnd}.
  function personStats(rows, data, rules, gapDays, segmentRows = rows) {
    const A = data.activity;
    const days = new Map();
    let dataEnd = -Infinity;
    for (const i of rows) {
      const person = A.person[i];
      if (!days.has(person)) days.set(person, []);
      days.get(person).push(A.day[i]);
      if (A.day[i] > dataEnd) dataEnd = A.day[i];
    }
    const counts = new Map();
    for (const i of segmentRows) counts.set(A.person[i], (counts.get(A.person[i]) || 0) + 1);
    const segmentOf = segmenter([...counts.values()], rules);
    const quarterOf = PS.periodScheme("quarter").key;
    const yearOf = PS.periodScheme("year").key;
    const stats = [];
    for (const [person, list] of days) {
      list.sort((a, b) => a - b);
      const quarters = new Set(list.map(quarterOf)).size;
      const years = [...new Set(list.map(yearOf))].sort((a, b) => a - b);
      let longestGap = 0, returns = 0;
      for (let k = 1; k < list.length; k++) {
        const gap = list[k] - list[k - 1];
        if (gap > longestGap) longestGap = gap;
        if (gap >= gapDays) returns += 1;
      }
      const last = list[list.length - 1];
      stats.push({
        person, first: list[0], last, activity: list.length, quarters, years,
        longestGap, returns, segment: segmentOf(list.length),
        current: dataEnd - last < gapDays,
      });
    }
    stats.sort((a, b) => b.activity - a.activity || a.person - b.person);
    return {stats, dataEnd};
  }

  // Document index -> its theme indexes, and which documents are tagged.
  let docIndex = null;
  function themeIndex(data) {
    if (docIndex) return docIndex;
    const themesOf = new Map();
    for (let k = 0; k < data.themes.doc.length; k++) {
      const d = data.themes.doc[k];
      if (!themesOf.has(d)) themesOf.set(d, []);
      themesOf.get(d).push(data.themes.theme[k]);
    }
    const tagged = new Uint8Array(data.docs.day.length);
    for (const d of data.themes.tagged) tagged[d] = 1;
    docIndex = {themesOf, tagged};
    return docIndex;
  }

  // Theme stats per period, rising/fading labels, and top contributors.
  // Mirrors trends.analyze(): activity counts toward its document's themes,
  // shares are of activity on tagged documents, and only periods with at
  // least half their documents tagged ("covered") get shares and trends.
  // Trends compare the last covered period with all earlier covered ones.
  function themeTrends(rows, data, scheme, {
    skipInProgress = false, coverage = 0.5, rise = 1.5, fade = 0.67, minDocs = 5, top = 5,
  } = {}) {
    const D = data.docs, A = data.activity;
    const {themesOf, tagged} = themeIndex(data);
    const nThemes = data.themes.name.length;
    const noThemes = [];

    // Periods run from the first document's to the last's; anything outside
    // falls in the nearest one, as trends.period_indexes() does.
    let minKey = Infinity, maxKey = -Infinity;
    const docKey = D.day.map(day => scheme.key(day));
    for (const k of docKey) { if (k < minKey) minKey = k; if (k > maxKey) maxKey = k; }
    if (scheme.kind === "release") { minKey = 0; maxKey = data.releases.day.length; }
    const n = maxKey - minKey + 1;
    if (!(n > 0)) return {periods: [], recent: null, earlier: [], trends: new Map(), contributors: new Map()};
    const indexOf = day => Math.max(0, Math.min(n - 1, scheme.key(day) - minKey));
    const grid = () => Array.from({length: nThemes}, () => new Array(n).fill(0));

    const docsIn = new Array(n).fill(0), taggedIn = new Array(n).fill(0);
    const themeDocs = grid();
    const firstDoc = new Array(nThemes).fill(null);  // {day, p}
    for (let d = 0; d < D.day.length; d++) {
      const p = Math.max(0, Math.min(n - 1, docKey[d] - minKey));
      docsIn[p] += 1;
      if (!tagged[d]) continue;
      taggedIn[p] += 1;
      for (const t of themesOf.get(d) || noThemes) {
        themeDocs[t][p] += 1;
        if (firstDoc[t] === null || D.day[d] < firstDoc[t].day) firstDoc[t] = {day: D.day[d], p};
      }
    }

    const commit = data.kinds.indexOf("commit");
    const activityIn = new Array(n).fill(0);
    const code = grid(), discussion = grid();
    const people = new Map();  // t * n + p -> Set of people
    const byPerson = Array.from({length: nThemes}, () => new Map());
    const lastDay = new Array(nThemes).fill(null);
    for (const i of rows) {
      const d = A.doc[i];
      if (d < 0 || !tagged[d]) continue;
      const p = indexOf(A.day[i]);
      activityIn[p] += 1;
      const isCode = A.kind[i] === commit;
      for (const t of themesOf.get(d) || noThemes) {
        (isCode ? code : discussion)[t][p] += 1;
        const cell = t * n + p;
        if (!people.has(cell)) people.set(cell, new Set());
        people.get(cell).add(A.person[i]);
        const c = byPerson[t].get(A.person[i]) || {code: 0, discussion: 0};
        if (isCode) c.code += 1; else c.discussion += 1;
        byPerson[t].set(A.person[i], c);
        if (lastDay[t] === null || A.day[i] > lastDay[t]) lastDay[t] = A.day[i];
      }
    }

    const covered = docsIn.map((docs, p) => docs > 0 && taggedIn[p] / docs >= coverage);
    const present = [];
    for (let t = 0; t < nThemes; t++) {
      if (themeDocs[t].some(Boolean) || code[t].some(Boolean) || discussion[t].some(Boolean)) present.push(t);
    }
    const name = t => data.themes.name[t];

    const periods = [];
    for (let p = 0; p < n; p++) {
      const key = p + minKey;
      const stats = [];
      for (const t of present) {
        const c = code[t][p], dsc = discussion[t][p];
        if (!(c || dsc || themeDocs[t][p])) continue;
        stats.push({
          theme: t, docs: themeDocs[t][p], code: c, discussion: dsc,
          people: people.has(t * n + p) ? people.get(t * n + p).size : 0,
          share: covered[p] && activityIn[p] ? (c + dsc) / activityIn[p] : null,
        });
      }
      stats.sort((a, b) => (b.code + b.discussion) - (a.code + a.discussion) || name(a.theme).localeCompare(name(b.theme)));
      const newKnown = covered.slice(0, p).some(Boolean);
      periods.push({
        key, label: scheme.label(key), short: scheme.short(key),
        partial: scheme.kind === "release" ? key === data.releases.day.length : p === n - 1,
        docs: docsIn[p], tagged: taggedIn[p], covered: covered[p], activity: activityIn[p],
        themes: stats,
        newThemes: newKnown ? present.filter(t => firstDoc[t] && firstDoc[t].p === p).map(name).sort() : [],
        newKnown,
      });
    }

    const candidates = periods.map((x, p) => p)
      .filter(p => covered[p] && activityIn[p] > 0 && !(skipInProgress && periods[p].partial));
    const recent = candidates.length ? candidates[candidates.length - 1] : null;
    const earlier = candidates.slice(0, -1);
    const trends = new Map();
    if (recent !== null && earlier.length) {
      const base = earlier.reduce((sum, p) => sum + activityIn[p], 0);
      for (const t of present) {
        const total = code[t][recent] + discussion[t][recent];
        const before = earlier.reduce((sum, p) => sum + code[t][p] + discussion[t][p], 0);
        const recentShare = activityIn[recent] ? total / activityIn[recent] : 0;
        const earlierShare = base ? before / base : 0;
        const docs = [...earlier, recent].reduce((sum, p) => sum + themeDocs[t][p], 0);
        let label;
        if (docs < minDocs) label = "too few";
        else if (earlierShare === 0) label = recentShare > 0 ? "rising" : "steady";
        else if (recentShare >= rise * earlierShare) label = "rising";
        else if (recentShare <= fade * earlierShare) label = "fading";
        else label = "steady";
        trends.set(t, {label, recentShare, earlierShare, docs});
      }
    }

    const contributors = new Map();
    for (const t of present) {
      const ranked = [...byPerson[t]].sort((a, b) =>
        (b[1].code + b[1].discussion) - (a[1].code + a[1].discussion) ||
        PS.personName(a[0]).localeCompare(PS.personName(b[0])));
      contributors.set(t, ranked.slice(0, top).map(([person, c]) => ({person, ...c})));
    }
    return {periods, recent, earlier, trends, contributors, present, firstDoc, lastDay, periodOf: indexOf};
  }

  return {
    periodCounts, personStats, themeIndex, themeTrends,
    SEGMENTS: ["core", "regular", "casual", "one-time"],
  };
})();
