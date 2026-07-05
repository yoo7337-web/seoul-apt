/* 대시보드 - 랭킹·평단가 추이·신축정렬·신고가 비중 */
(function () {
  "use strict";
  const DATA = "data/";
  const $ = (id) => document.getElementById(id);
  const COLORS = ["#ff7e00", "#2563eb", "#10b981", "#a855f7", "#ef4444",
                  "#0ea5e9", "#f59e0b", "#84cc16", "#ec4899", "#64748b"];

  let meta = null, dash = null, inited = false;
  const trendOn = new Set();   // 켜져 있는 구 lawd_cd

  async function init() {
    if (inited) return true;
    [meta, dash] = await Promise.all([
      fetchJSON(DATA + "meta.json").catch(() => null),
      fetchJSON(DATA + "dashboard.json").catch(() => null),
    ]);
    if (!meta) return false;
    inited = true;
    renderRankTable();
    initTrend();
    initNewOld();
    renderPeakShare();
    renderRebChart();
    return true;
  }

  // 지도 페이지의 분할 패널에서 호출: 최초 1회 데이터 로드 + 차트 크기 재계산
  window.SeoulDash = {
    open: async () => {
      const ok = await init();
      if (ok) setTimeout(() => { renderTrend(); renderPeakShare(); renderRebChart(); }, 60);
    },
  };

  // 독립 대시보드 페이지(body.page)면 자동 렌더
  if (document.body.classList.contains("page")) {
    document.addEventListener("DOMContentLoaded", init);
  }

  // ── 1) 구별 랭킹 ────────────────────────────────────────────────────
  function renderRankTable() {
    const ranks = meta.rankings || [];
    let html = `<table class="rank-table"><thead><tr>
      <th>#</th><th>자치구</th><th>평단가(만원/평)</th><th>6개월 변동</th><th>거래건수</th>
      </tr></thead><tbody>`;
    ranks.forEach((r, i) => {
      const chg = r.change_6m;
      const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
      html += `<tr><td>${i + 1}</td><td>${r.name}</td>
        <td>${r.ppy_median ? Math.round(r.ppy_median).toLocaleString() : "-"}</td>
        <td class="${cls}">${chg != null ? (chg > 0 ? "+" : "") + chg + "%" : "-"}</td>
        <td>${(r.sale_count || 0).toLocaleString()}</td></tr>`;
    });
    $("rank-table-wrap").innerHTML = html + "</tbody></table>";
    $("rank-desc").textContent =
      `기준: ${meta.last_updated_display || "-"} · 만원/평`;
  }

  // ── 2) 평단가 추이 ──────────────────────────────────────────────────
  function initTrend() {
    if (!dash || !dash.ppy_trend) return;
    const ranks = meta.rankings || [];
    // 기본: 랭킹 상위 5개 구 켜기
    ranks.slice(0, 5).forEach((r) => trendOn.add(r.lawd_cd));
    const chips = $("trend-chips");
    ranks.forEach((r) => {
      const b = document.createElement("button");
      b.className = "d-chip" + (trendOn.has(r.lawd_cd) ? " on" : "");
      b.textContent = r.name;
      b.addEventListener("click", () => {
        if (trendOn.has(r.lawd_cd)) trendOn.delete(r.lawd_cd);
        else trendOn.add(r.lawd_cd);
        b.classList.toggle("on");
        renderTrend();
      });
      chips.appendChild(b);
    });
    renderTrend();
  }

  function renderTrend() {
    const names = {};
    (meta.rankings || []).forEach((r) => { names[r.lawd_cd] = r.name; });
    const sel = [...trendOn];
    const months = new Set();
    sel.forEach((cd) => (dash.ppy_trend[cd] || []).forEach((p) => months.add(p.m)));
    const labels = [...months].sort();
    const datasets = sel.map((cd, i) => {
      const map = {};
      (dash.ppy_trend[cd] || []).forEach((p) => { map[p.m] = p.p; });
      return { label: names[cd] || cd, color: COLORS[i % COLORS.length],
               data: labels.map((m) => map[m] ?? null) };
    });
    SeoulCharts.line("trend-chart", labels, datasets);
  }

  // ── 3) 신축→구축 ────────────────────────────────────────────────────
  function initNewOld() {
    const sel = $("no-district");
    (meta.districts || []).forEach((d) => {
      const o = document.createElement("option");
      o.value = d.lawd_cd; o.textContent = d.name;
      sel.appendChild(o);
    });
    sel.addEventListener("change", () => renderNewOld(sel.value));
    if (meta.districts && meta.districts.length) {
      sel.value = meta.districts[0].lawd_cd;
      renderNewOld(sel.value);
    }
  }

  async function renderNewOld(lawd) {
    let d;
    try { d = await fetchJSON(`${DATA}districts/${lawd}.json`); }
    catch { $("no-table-wrap").innerHTML = '<div class="empty">데이터 없음</div>'; return; }
    const list = (d.complexes || [])
      .filter((c) => c.build_year)
      .sort((a, b) => b.build_year - a.build_year);
    let html = `<table class="rank-table"><thead><tr>
      <th>단지</th><th>법정동</th><th>준공</th><th>연차</th><th>세대수</th>
      <th>매매중앙값</th><th>평단가</th></tr></thead><tbody>`;
    const nowY = new Date().getFullYear();
    list.forEach((c) => {
      html += `<tr><td>${c.apt}</td><td>${c.umd || "-"}</td>
        <td>${c.build_year}</td><td>${nowY - c.build_year}년</td>
        <td>${c.households ? c.households.toLocaleString() : "-"}</td>
        <td>${SeoulCharts.fmt(c.sale_median)}</td>
        <td>${c.ppy_median ? Math.round(c.ppy_median).toLocaleString() : "-"}</td></tr>`;
    });
    $("no-table-wrap").innerHTML = html + "</tbody></table>";
  }

  // ── 4) 신고가 비중 ──────────────────────────────────────────────────
  function renderPeakShare() {
    if (!dash || !dash.peak_share || !dash.peak_share.length) return;
    $("ps-days").textContent = `(최근 ${dash.peak_share_days || 90}일)`;
    const rows = dash.peak_share;
    SeoulCharts.bar("peak-chart",
      rows.map((r) => `${r.name} (${r.peaks}/${r.total})`),
      rows.map((r) => r.share),
      { horizontal: true, label: "신고가 비중", unit: "%" });
  }

  // ── 5) 부동산원 가격지수(서울) ──────────────────────────────────────
  let rebData = null;
  async function renderRebChart() {
    if (!document.getElementById("reb-chart")) return;
    if (!rebData) {
      try { rebData = await fetchJSON(DATA + "reb/seoul_index.json"); }
      catch { return; }
    }
    const stats = Object.keys(rebData || {});
    if (!stats.length || !window.SeoulCharts) return;
    const colors = ["#ff7e00", "#2563eb"];
    let labels = [];
    const datasets = [];
    stats.forEach((stat, i) => {
      const regions = rebData[stat];
      const seoul = regions["서울"] || regions[Object.keys(regions)[0]] || [];
      if (seoul.length > labels.length) labels = seoul.map((p) => p.period);
      datasets.push({ label: stat, color: colors[i % colors.length],
        data: seoul.map((p) => p.value) });
    });
    SeoulCharts.line("reb-chart", labels, datasets);
  }

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
})();
