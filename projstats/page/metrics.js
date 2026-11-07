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

  return {periodCounts};
})();
