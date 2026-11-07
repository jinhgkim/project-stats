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
        activity: 0, partial: key === maxKey,
      });
    }
    const lastSeen = new Map();
    for (const list of days.values()) {
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
        if (prev === null) row.new += 1;
        else if (list[i] - prev >= gapDays) row.returning += 1;
        else row.continuing += 1;
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

  // rules: {core, regular} quarter thresholds. Mirrors retention._segment().
  function segmentOf(activity, quarters, rules) {
    if (activity === 1) return "one-time";
    if (quarters >= rules.core) return "core";
    if (quarters >= rules.regular) return "regular";
    return "casual";
  }

  // Cadence per person over `rows`. Mirrors retention.person_stats(): the
  // segment counts distinct calendar quarters, and "current" means active
  // within gapDays of the last day in `rows`. Returns {stats, dataEnd}.
  function personStats(rows, data, rules, gapDays) {
    const A = data.activity;
    const days = new Map();
    let dataEnd = -Infinity;
    for (const i of rows) {
      const person = A.person[i];
      if (!days.has(person)) days.set(person, []);
      days.get(person).push(A.day[i]);
      if (A.day[i] > dataEnd) dataEnd = A.day[i];
    }
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
        longestGap, returns, segment: segmentOf(list.length, quarters, rules),
        current: dataEnd - last < gapDays,
      });
    }
    stats.sort((a, b) => b.activity - a.activity || a.person - b.person);
    return {stats, dataEnd};
  }

  const COHORT_OFFSETS = [1, 2, 5];

  // People grouped by the year of their first activity, and how many were
  // active 1, 2, and 5 years later (null until that year is complete).
  // Mirrors retention.cohorts().
  function cohorts(stats, dataEnd) {
    const lastComplete = PS.periodScheme("year").key(dataEnd) - 1;
    const groups = new Map();
    for (const s of stats) {
      const year = s.years[0];
      if (!groups.has(year)) groups.set(year, []);
      groups.get(year).push(s);
    }
    return [...groups.keys()].sort((a, b) => a - b).map(year => {
      const members = groups.get(year);
      const after = {};
      for (const n of COHORT_OFFSETS) {
        after[n] = year + n > lastComplete ? null
          : members.filter(s => s.years.includes(year + n)).length;
      }
      return {
        year, size: members.length,
        oneTime: members.filter(s => s.segment === "one-time").length,
        after, members,
      };
    });
  }

  return {periodCounts, personStats, cohorts, COHORT_OFFSETS, SEGMENTS: ["core", "regular", "casual", "one-time"]};
})();
