/* Chart.js 래퍼 - 단지 추세, 구 추세, 부동산원 지수 */
(function (global) {
  const palette = {
    sale: "#2563eb", jeonse: "#10b981", wolse: "#f59e0b",
    gongsi: "#a855f7", index: "#ef4444",
  };
  let charts = {};

  function destroy(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  }

  function themeColor() {
    return getComputedStyle(document.body).getPropertyValue("--muted") || "#888";
  }

  const hasZoom = () => !!(window.Chart && Chart.registry
    && Chart.registry.plugins.get("zoom"));

  function line(canvasId, labels, datasets, opts = {}) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    const zoomable = opts.zoom !== false && hasZoom();
    charts[canvasId] = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: datasets.map(d => ({
        label: d.label, data: d.data, borderColor: d.color,
        backgroundColor: d.color + "22", tension: 0.25, spanGaps: true,
        pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, yAxisID: d.axis || "y",
      })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,   // 백그라운드 탭/캡처에서 rAF 정지로 빈 캔버스가 되는 것 방지
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: themeColor(), font: { size: 11 }, boxWidth: 12 } },
          tooltip: { callbacks: {
            label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}`,
          } },
          zoom: zoomable ? {
            zoom: {
              drag: { enabled: true, backgroundColor: "rgba(255,126,0,.15)",
                      borderColor: "#ff7e00", borderWidth: 1 },
              wheel: { enabled: true, speed: 0.1 },
              mode: "x",
            },
          } : undefined,
        },
        scales: Object.assign({
          x: { ticks: { color: themeColor(), maxTicksLimit: 8, font: { size: 10 } },
               grid: { display: false } },
          y: { ticks: { color: themeColor(), font: { size: 10 },
               callback: (v) => fmt(v) }, grid: { color: themeColor() + "22" } },
        }, opts.scales || {}),
      },
    });
    if (zoomable) ensureZoomControls(canvasId);
  }

  // 차트 위에 기간 프리셋(1/3/5/10년/전체) + 초기화 컨트롤 바를 1회 생성
  function ensureZoomControls(canvasId) {
    const canvas = document.getElementById(canvasId);
    const wrap = canvas && canvas.parentElement;      // .chart-tall / .chart-wrap
    if (!wrap || !wrap.parentElement) return;
    let bar = wrap.previousElementSibling;
    if (bar && bar.classList.contains("chart-ctrl") && bar.dataset.for === canvasId) {
      clearActive(bar); return;   // 재렌더 시 전체범위로 → 활성표시 해제
    }
    bar = document.createElement("div");
    bar.className = "chart-ctrl"; bar.dataset.for = canvasId;
    [["1년", 12], ["3년", 36], ["5년", 60], ["10년", 120], ["전체", 0]].forEach(([t, m]) => {
      const b = document.createElement("button");
      b.className = "d-chip"; b.textContent = t;
      b.addEventListener("click", () => applyPreset(canvasId, m, b));
      bar.appendChild(b);
    });
    const r = document.createElement("button");
    r.className = "d-chip reset"; r.textContent = "↺ 초기화";
    r.addEventListener("click", () => resetRange(canvasId, bar));
    bar.appendChild(r);
    wrap.parentElement.insertBefore(bar, wrap);
  }

  function clearActive(bar) {
    bar.querySelectorAll(".d-chip.on").forEach((x) => x.classList.remove("on"));
  }

  function applyPreset(canvasId, months, btn) {
    const c = charts[canvasId];
    if (!c) return;
    const labels = c.data.labels || [];
    if (c.resetZoom) c.resetZoom("none");           // 드래그 확대 상태 제거
    if (!months || months >= labels.length) {
      c.options.scales.x.min = undefined; c.options.scales.x.max = undefined;
    } else {
      c.options.scales.x.min = labels[labels.length - months];
      c.options.scales.x.max = labels[labels.length - 1];
    }
    c.update("none");
    clearActive(btn.parentElement); btn.classList.add("on");
  }

  function resetRange(canvasId, bar) {
    const c = charts[canvasId];
    if (!c) return;
    if (c.resetZoom) c.resetZoom("none");           // 드래그 확대 먼저 제거
    c.options.scales.x.min = undefined;             // 그다음 프리셋 범위 해제
    c.options.scales.x.max = undefined;
    c.update("none");
    clearActive(bar);
  }

  function bar(canvasId, labels, values, opts = {}) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    const color = opts.color || "#ff7e00";
    charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{
        label: opts.label || "", data: values,
        backgroundColor: color + "cc", borderColor: color,
        borderWidth: 1, borderRadius: 4,
      }] },
      options: {
        indexAxis: opts.horizontal ? "y" : "x",
        responsive: true, maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: (c) => `${opts.label || ""} ${c.parsed[opts.horizontal ? "x" : "y"]}${opts.unit || ""}`,
          } },
        },
        scales: {
          x: { ticks: { color: themeColor(), font: { size: 10 } },
               grid: { color: opts.horizontal ? themeColor() + "22" : "transparent" } },
          y: { ticks: { color: themeColor(), font: { size: 10 } },
               grid: { color: opts.horizontal ? "transparent" : themeColor() + "22" } },
        },
      },
    });
  }

  // 산점도 - datasets: [{label, color, data:[{x,y,meta}]}]. 점 클릭 시 opts.onClick(meta)
  function scatter(canvasId, datasets, opts = {}) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    charts[canvasId] = new Chart(ctx, {
      type: "scatter",
      data: { datasets: datasets.map((d) => ({
        label: d.label, data: d.data,
        backgroundColor: d.color + "aa", borderColor: d.color,
        pointRadius: 3.5, pointHoverRadius: 6,
      })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        onClick: (e, els) => {
          if (!els.length || !opts.onClick) return;
          const el = els[0];
          const meta = charts[canvasId].data.datasets[el.datasetIndex]
            .data[el.index].meta;
          if (meta) opts.onClick(meta);
        },
        plugins: {
          legend: { labels: { color: themeColor(), font: { size: 11 }, boxWidth: 12 } },
          tooltip: { callbacks: {
            label: (c) => {
              const m = c.raw.meta || {};
              return `${m.apt || ""} (${c.parsed.x}${opts.xUnit || ""}, ${c.parsed.y}${opts.yUnit || ""})`;
            },
          } },
        },
        scales: {
          x: { title: { display: !!opts.xLabel, text: opts.xLabel || "",
                        color: themeColor(), font: { size: 11 } },
               min: opts.xMin, max: opts.xMax,
               ticks: { color: themeColor(), font: { size: 10 } },
               grid: { color: themeColor() + "22" } },
          y: { title: { display: !!opts.yLabel, text: opts.yLabel || "",
                        color: themeColor(), font: { size: 11 } },
               min: opts.yMin, max: opts.yMax,
               ticks: { color: themeColor(), font: { size: 10 } },
               grid: { color: themeColor() + "22" } },
        },
      },
    });
  }

  function fmt(v) {
    if (v == null) return "-";
    if (v >= 10000) return (v / 10000).toFixed(1).replace(/\.0$/, "") + "억";
    return Math.round(v).toLocaleString();
  }

  global.SeoulCharts = { line, bar, scatter, destroy, palette, fmt };
})(window);
