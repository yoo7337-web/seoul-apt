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

  function line(canvasId, labels, datasets, opts = {}) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
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
        },
        scales: Object.assign({
          x: { ticks: { color: themeColor(), maxTicksLimit: 8, font: { size: 10 } },
               grid: { display: false } },
          y: { ticks: { color: themeColor(), font: { size: 10 },
               callback: (v) => fmt(v) }, grid: { color: themeColor() + "22" } },
        }, opts.scales || {}),
      },
    });
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

  function fmt(v) {
    if (v == null) return "-";
    if (v >= 10000) return (v / 10000).toFixed(1).replace(/\.0$/, "") + "억";
    return Math.round(v).toLocaleString();
  }

  global.SeoulCharts = { line, bar, destroy, palette, fmt };
})(window);
