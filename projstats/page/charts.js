// Shared chart pieces for views: size, SVG frame, axes, hit targets, and the
// details header, plus whole chart types (stacked columns, heatmap). Each
// view shapes its own data and keeps what is particular to it.

PS.charts = (() => {
  // The chart's width in px: the plot's, or the card's before it is laid out.
  function widthOf(figure) {
    return Math.max(320, figure.plot.clientWidth || figure.root.clientWidth - 32);
  }

  function empty(figure, text) {
    figure.plot.replaceChildren(PS.el("p", {class: "empty"}, text));
  }

  // label: the chart's accessible name; null hides the SVG from screen
  // readers (e.g. a header strip of labels).
  function svg(width, height, label) {
    const node = d3.create("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("height", height);
    return label === null ? node.attr("aria-hidden", "true") : node.attr("role", "group").attr("aria-label", label);
  }

  // An SVG plus the inner group, offset by the margins.
  function frame(width, height, margin, label) {
    const node = svg(width, height, label);
    const g = node.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    return {svg: node, g, innerW: width - margin.left - margin.right, innerH: height - margin.top - margin.bottom};
  }

  // Gridlines at `values`, and the left axis without its domain line.
  function yAxis(g, y, innerW, {values, format}) {
    g.append("g").attr("class", "grid")
      .selectAll("line").data(values).join("line")
      .attr("x1", 0).attr("x2", innerW).attr("y1", d => y(d)).attr("y2", d => y(d));
    g.append("g").attr("class", "axis")
      .call(d3.axisLeft(y).tickValues(values).tickFormat(format).tickSize(0).tickPadding(6))
      .call(a => a.select(".domain").remove());
  }

  // Label every nth band, so labels sit about 56px apart.
  function labelEvery(step) {
    return Math.max(1, Math.ceil(56 / step));
  }

  // The bottom axis of a band scale, with as many labels as fit.
  function bandAxis(g, x, innerH, label) {
    const every = labelEvery(x.step());
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickValues(x.domain().filter((k, i) => i % every === 0))
        .tickSize(0).tickPadding(8).tickFormat(label));
  }

  // Hit targets for a chart's marks (nodes: d3 selections the view drew). One
  // tab stop at `current`; the [prev, next] `keys`, Home, and End move between
  // them. Hover and focus show the tooltip, via show(i, anchor). With
  // activate(i), they are buttons: click, Enter, and Space call it. onFocus(i)
  // lets the view remember the focused one across re-renders. Returns
  // refocus(), to call once the chart is in the page: after Enter re-renders
  // the view, it focuses the target at `current` again.
  function hits(figure, nodes, {keys, current, label, show, activate, onFocus}) {
    nodes.forEach((node, i) => {
      node.attr("role", activate ? "button" : "img").attr("aria-label", label(i))
        .on("pointermove", event => show(i, event))
        .on("focus", event => {
          if (onFocus) onFocus(i);
          show(i, event.currentTarget);
        })
        .on("pointerleave blur", PS.hideTooltip);
      if (!activate) return;
      node.on("click", () => {
        activate(i);
        if (!figure.details.hidden) figure.details.scrollIntoView({behavior: "smooth", block: "nearest"});
      }).on("keydown", event => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        figure.refocus = true;
        activate(i);
      });
    });
    const elements = nodes.map(node => node.node());
    PS.rovingFocus(elements, current, keys[0], keys[1]);
    return () => {
      if (!figure.refocus) return;
      figure.refocus = false;
      elements[current].focus();
    };
  }

  // The outline around the chosen column or zone.
  function outline(g, {x, y, width, height, rx}) {
    const rect = g.append("rect").attr("x", x).attr("y", y).attr("width", width).attr("height", height);
    if (rx !== undefined) rect.attr("rx", rx);
    return rect.attr("fill", "none").attr("stroke", "var(--text-primary)").attr("stroke-width", 1.5)
      .attr("pointer-events", "none");
  }

  // The details area's title row: the title, any `extra` buttons, and Close.
  function detailsHead(title, onClose, extra = []) {
    const close = PS.el("button", {type: "button"}, "Close");
    close.onclick = onClose;
    return PS.el("div", {class: "details-head"}, PS.el("h3", {}, title), ...extra, close);
  }

  // A colored dot for a list row or a legend key.
  function dot(color) {
    return PS.el("span", {
      class: "status on", style: `background: ${color}; border-color: ${color}`, "aria-hidden": "true",
    });
  }

  // Words for a column's sort order, read out by screen readers.
  const ORDER_WORDS = {
    text: {asc: "A to Z", desc: "Z to A"},
    date: {asc: "oldest first", desc: "newest first"},
    count: {asc: "fewest first", desc: "most first"},
  };

  // A list table with sortable columns, as in the activity panes. columns:
  // [{key, label, cell(item): text or nodes, order: "text" | "date" | "count"}].
  // `items` come already ordered by `sort` ({key, dir}) and cut to length; a
  // click on a header calls onSort(key).
  function listTable(items, {columns, sort, onSort, className}) {
    const header = ({key, label, order = "text"}) => {
      const on = sort.key === key;
      const words = ORDER_WORDS[order][sort.dir];
      const button = PS.el("button", {
        type: "button", class: "sort", "aria-label": on ? `${label}, ${words}. Click to reverse.` : `Sort by ${label}`,
      }, label, PS.el("span", {class: on ? (sort.dir === "asc" ? "chev up" : "chev") : "sort-none", "aria-hidden": "true"}));
      button.onclick = () => onSort(key);
      return PS.el("th", {scope: "col", "aria-sort": on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}, button);
    };
    return PS.el("div", {class: "table-wrap"}, PS.el("table", {class: className},
      PS.el("thead", {}, PS.el("tr", {}, columns.map(header))),
      PS.el("tbody", {}, items.map(item => PS.el("tr", {}, columns.map(c => PS.el("td", {}, c.cell(item))))))));
  }

  // A body SVG that scrolls both ways, under a header SVG and beside a names
  // SVG that follow it; returns the scrolling element. labelW is the names'
  // width.
  function scrollArea(figure, {labelW, header, names, body}) {
    const head = PS.el("div", {class: "hm-head"}, header.node());
    const side = PS.el("div", {class: "hm-names"}, names.node());
    const scroll = PS.el("div", {class: "scroll"}, body.node());
    scroll.addEventListener("scroll", () => {
      PS.hideTooltip();
      head.scrollLeft = scroll.scrollLeft;
      side.scrollTop = scroll.scrollTop;
    }, {passive: true});
    figure.plot.replaceChildren(PS.el("div", {class: "hm-grid", style: `grid-template-columns: ${labelW}px minmax(0, 1fr)`},
      PS.el("div"), head, side, scroll));
    // The scrollbars take room from the cells; leave the same in the others.
    head.style.paddingRight = `${scroll.offsetWidth - scroll.clientWidth}px`;
    side.style.paddingBottom = `${scroll.offsetHeight - scroll.clientHeight}px`;
    return scroll;
  }

  // A path for a bar with only its top corners rounded.
  function topRounded(x0, y0, w, h, r) {
    r = Math.min(r, h, w / 2);
    return `M${x0},${y0 + h}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}` +
      `H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + h}Z`;
  }

  // Stacked columns, one per item, each series stacked bottom up. Options:
  //   items, key(item), tick(key): the axis label,
  //   series: [{id, name, color}], value(item, series), total(item): the column's height,
  //   faded(item): drawn lighter (e.g. a partial period),
  //   labelSuffix: added to the direct labels on the last column (dropped when
  //     they don't fit; then the labels go, and the legend names the colors),
  //   markers: [{key, label}] vertical lines at the left edge of a column,
  //   label: the chart's accessible name, itemLabel(item), tooltip(item, anchor),
  //   activate(item): what choosing a column does, picked: the chosen item or null.
  // The focused column is kept on figure.focusKey across re-renders.
  function columns(figure, {items, key, tick, series, value, total, faded = () => false, labelSuffix = "",
                            markers = [], label, itemLabel, tooltip, activate, picked = null}) {
    const width = widthOf(figure);
    const height = 320;
    const top = 36, bottom = 26, left = 40;
    const innerH = height - top - bottom;
    const yMax = d3.max(items, total) || 1;
    const y = d3.scaleLinear([0, yMax], [innerH, 0]).nice();

    // Direct labels on the last column, where they fit; the right margin is
    // sized to the longest one, so the plot keeps most of the width.
    const last = items[items.length - 1];
    const labelsFor = suffix => {
      const out = [];
      let base = 0;
      for (const s of series) {
        const v = value(last, s);
        if (v > 0 && y(base) - y(base + v) >= 14) {
          out.push({y: y(base + v / 2), text: `${s.name} ${v}${suffix}`});
        }
        base += v;
      }
      return out;
    };
    const space = list => 16 + Math.max(0, ...list.map(d => PS.textWidth(d.text, 12)));
    const direct = [labelsFor(labelSuffix), labelsFor("")].find(l => space(l) <= width * 0.22) || [];
    const margin = {top, right: space(direct), bottom, left};
    const {svg: node, g, innerW} = frame(width, height, margin, label);

    const x = d3.scaleBand(items.map(key), [0, innerW]).paddingInner(0.25).paddingOuter(0.1);
    const barW = Math.max(1, Math.min(24, x.bandwidth()));
    const barX = item => x(key(item)) + (x.bandwidth() - barW) / 2;

    yAxis(g, y, innerW, {values: y.ticks(5), format: y.tickFormat(5, "~s")});
    bandAxis(g, x, innerH, tick);

    // A 2px surface gap between segments, 4px round on top.
    const bars = g.append("g");
    for (const item of items) {
      const parts = series.filter(s => value(item, s) > 0);
      let base = 0;
      parts.forEach((s, i) => {
        const v = value(item, s);
        const y0 = y(base) - (i === 0 ? 0 : 1);
        const y1 = y(base + v) + (i === parts.length - 1 ? 0 : 1);
        base += v;
        const h = y0 - y1;
        if (h <= 0) return;
        const shape = i === parts.length - 1
          ? bars.append("path").attr("d", topRounded(barX(item), y1, barW, h, 4))
          : bars.append("rect").attr("x", barX(item)).attr("y", y1).attr("width", barW).attr("height", h);
        shape.attr("fill", s.color).attr("opacity", faded(item) ? 0.45 : 1);
      });
    }

    const markerG = g.append("g").attr("class", "marker");
    markers.forEach((m, i) => {
      markerG.append("line").attr("x1", x(m.key)).attr("x2", x(m.key))
        .attr("y1", -32 + i * 14).attr("y2", innerH);
    });
    PS.markerLabels(markerG, markers, x, -24, -margin.left, innerW + margin.right);

    for (const d of direct) {
      g.append("text").attr("class", "label")
        .attr("x", barX(last) + barW + 6).attr("y", d.y).attr("dominant-baseline", "middle")
        .text(d.text);
    }

    // Each column's full height is its hit target.
    if (!items.some(item => key(item) === figure.focusKey)) figure.focusKey = key(last);
    const hit = g.append("g");
    const columnX = item => x(key(item)) - (x.step() - x.bandwidth()) / 2;
    const refocus = hits(figure, items.map(item => hit.append("rect").attr("class", "hit clickable")
      .attr("x", columnX(item)).attr("y", 0).attr("width", x.step()).attr("height", innerH)), {
      keys: ["ArrowLeft", "ArrowRight"],
      current: items.findIndex(item => key(item) === figure.focusKey),
      label: i => itemLabel(items[i]),
      show: (i, anchor) => tooltip(items[i], anchor),
      activate: activate && (i => activate(items[i])),
      onFocus: i => { figure.focusKey = key(items[i]); },
    });

    if (picked) outline(g, {x: columnX(picked), y: 0, width: x.step(), height: innerH, rx: 3});

    figure.plot.replaceChildren(node.node());
    refocus();
  }

  // A heatmap: a row per item and a cell per column. The cells scroll under a
  // fixed header of column labels and beside fixed row labels; columns never
  // get narrower than their labels. Up and down move between rows; left and
  // right move a cursor between cells; Enter, Space, or a click chooses a
  // cell. Callbacks get row index i and column index k. Options:
  //   rows, cols, rowLabel(i), rowCurrent(i): the label in bold,
  //   colLabel(k), colNote(k): a second header line, or null,
  //   cell(i, k): {text, bin, faded} or null (also for k outside the columns);
  //     bin picks the color step, var(--seq-<bin + 1>),
  //   label: the chart's accessible name, rowLabelAria(i),
  //   tooltip(i, k, anchor): k is undefined when hovering outside the columns,
  //   onPick(i, k), picked: {row, col} or null, focusRow: the default tab stop.
  // The cursor's column (figure.col) and the scroll position survive re-renders;
  // a first draw, or a change in the number of columns, scrolls to the last.
  function heatmap(figure, {rows, cols, rowLabel, rowCurrent, colLabel, colNote, cell, label, rowLabelAria,
                            tooltip, onPick, picked = null, focusRow = 0}) {
    const scrolled = figure.plot.querySelector(".scroll");
    const scrollTop = scrolled ? scrolled.scrollTop : 0;
    if (figure.col === undefined || figure.col >= cols.length) figure.col = cols.length - 1;

    const width = widthOf(figure);
    const maxNameW = Math.min(220, Math.round(width * 0.4));
    const name = i => PS.fitText(rowLabel(i), 12, maxNameW);
    const x0 = 8 + Math.max(...rows.map((_, i) => PS.textWidth(name(i), 12)));
    const headW = Math.max(...cols.map((_, k) => Math.max(PS.textWidth(colLabel(k), 11), PS.textWidth(colNote(k) || "", 11))));
    const cellW = Math.min(110, Math.max(34, headW + 8, (width - x0) / cols.length));
    const gridW = cols.length * cellW;
    const rowH = 24, top = 34;
    const height = rows.length * rowH;
    const sized = (node, w) => node.style("width", `${w}px`);

    const header = sized(svg(gridW, top, null), gridW);
    cols.forEach((_, k) => {
      const cx = k * cellW + cellW / 2;
      header.append("text").attr("x", cx).attr("y", 14).attr("text-anchor", "middle").text(colLabel(k));
      const note = colNote(k);
      if (note) header.append("text").attr("x", cx).attr("y", 27).attr("text-anchor", "middle").text(note);
    });
    const names = sized(svg(x0, height, null), x0);
    const body = sized(svg(gridW, height, label), gridW);

    const colAt = event => Math.floor(d3.pointer(event, body.node())[0] / cellW);
    const choose = (i, k, keyboard) => {
      if (!cell(i, k)) return;
      PS.hideTooltip();
      figure.col = k;
      figure.refocusRow = keyboard ? i : undefined;
      onPick(i, k);
    };

    const targets = [];
    rows.forEach((_, i) => {
      const y = i * rowH;
      const mid = y + rowH / 2;
      const g = body.append("g");
      const side = names.append("g");
      side.append("text").attr("class", rowCurrent(i) ? "label current" : "label")
        .attr("x", 0).attr("y", mid).attr("dominant-baseline", "middle").text(name(i));
      side.append("rect").attr("class", "hit").attr("x", 0).attr("y", y).attr("width", x0).attr("height", rowH)
        .on("pointermove", event => tooltip(i, undefined, event))
        .on("pointerleave", PS.hideTooltip);
      cols.forEach((_, k) => {
        const c = cell(i, k);
        const x = k * cellW;
        if (!c) return;
        g.append("rect").attr("x", x + 1).attr("y", y + 1).attr("width", cellW - 2).attr("height", rowH - 2)
          .attr("rx", 3).attr("fill", `var(--seq-${c.bin + 1})`).attr("opacity", c.faded ? 0.6 : 1);
        g.append("text").attr("class", c.bin >= 3 ? "cell-ink-inverse" : "cell-ink")
          .attr("x", x + cellW / 2).attr("y", mid).attr("text-anchor", "middle")
          .attr("dominant-baseline", "middle").text(c.text);
      });

      // k: the column to describe; from the pointer when left out.
      const show = (anchor, k) => {
        if (k === undefined && anchor instanceof Event && "clientX" in anchor) {
          k = colAt(anchor);
          anchor.currentTarget.style.cursor = cell(i, k) ? "pointer" : "";
        }
        tooltip(i, k, anchor);
      };
      targets.push(g.append("rect").attr("class", "hit")
        .attr("x", 0).attr("y", y).attr("width", gridW).attr("height", rowH)
        .attr("role", "button")
        .attr("aria-label", rowLabelAria(i))
        .on("pointermove", show)
        .on("click", event => choose(i, colAt(event), false))
        .on("keydown", event => {
          const step = {ArrowLeft: -1, ArrowRight: 1}[event.key];
          if (step !== undefined) {
            event.preventDefault();
            figure.col = Math.max(0, Math.min(cols.length - 1, figure.col + step));
            place(i);
            show(event.currentTarget, figure.col);
          } else if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            choose(i, figure.col, true);
          }
        })
        .on("focus", event => { place(i); show(event.currentTarget, figure.col); })
        .on("pointerleave blur", PS.hideTooltip)
        .on("blur.cursor", () => cursor.attr("display", "none")).node());
    });

    // Marks above the rows: the chosen cell, and the cell the arrow keys are on.
    const mark = (cls, k, i, stroke, w) => body.append("rect").attr("class", cls)
      .attr("x", k * cellW + 1).attr("y", i * rowH + 1).attr("width", cellW - 2).attr("height", rowH - 2)
      .attr("rx", 3).attr("fill", "none").attr("stroke", stroke).attr("stroke-width", w)
      .attr("pointer-events", "none");
    if (picked) mark("picked", picked.col, picked.row, "var(--text-primary)", 1.5);
    const cursor = mark("cursor", 0, 0, "var(--series-1)", 2).attr("display", "none");
    const place = i => {
      const left = figure.col * cellW;
      cursor.attr("display", null).attr("x", left + 1).attr("y", i * rowH + 1);
      scroll.scrollLeft = Math.min(left, Math.max(scroll.scrollLeft, left + cellW - scroll.clientWidth));
    };

    PS.rovingFocus(targets, figure.refocusRow !== undefined ? figure.refocusRow : focusRow, "ArrowUp", "ArrowDown");
    const scroll = scrollArea(figure, {labelW: x0, header, names, body});
    scroll.scrollTop = scrollTop;
    scroll.scrollLeft = figure.scrollCols === cols.length ? figure.scrollLeft : scroll.scrollWidth;
    figure.scrollCols = cols.length;
    scroll.addEventListener("scroll", () => { figure.scrollLeft = scroll.scrollLeft; }, {passive: true});
    if (figure.refocusRow !== undefined) {
      targets[figure.refocusRow].focus();
      figure.refocusRow = undefined;
    }
  }

  return {
    width: widthOf, empty, svg, frame, yAxis, labelEvery, bandAxis, hits, outline, detailsHead,
    dot, listTable, scrollArea, columns, heatmap,
  };
})();
