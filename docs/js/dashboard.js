/* 대시보드 - 랭킹·평단가 추이·신축정렬·신고가 비중 */
(function () {
  "use strict";
  const DATA = "data/";
  const $ = (id) => document.getElementById(id);
  const COLORS = ["#ff7e00", "#2563eb", "#10b981", "#a855f7", "#ef4444",
                  "#0ea5e9", "#f59e0b", "#84cc16", "#ec4899", "#64748b"];

  let meta = null, dash = null, inited = false;
  const localSel = new Set();   // 독립 페이지(지도 없음)용 로컬 선택

  async function init() {
    if (inited) return true;
    [meta, dash] = await Promise.all([
      fetchJSON(DATA + "meta.json").catch(() => null),
      fetchJSON(DATA + "dashboard.json").catch(() => null),
    ]);
    if (!meta) return false;
    inited = true;
    // 지도(app.js)의 선택 변경을 대시보드에 반영
    if (window.SeoulMap) window.SeoulMap.onChange = () => refresh();
    refresh();
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

  // ── 공유 선택(지도 있으면 SeoulMap, 없으면 로컬) ────────────────────
  const hasMap = () => !!window.SeoulMap;
  const getSel = () => hasMap() ? window.SeoulMap.getSelected() : new Set(localSel);
  function applySel(set) {
    if (hasMap()) window.SeoulMap.setSelected(set);   // → onChange → refresh
    else { localSel.clear(); set.forEach((x) => localSel.add(x)); refresh(); }
  }
  function toggleSel(lawd) {
    const s = getSel(); s.has(lawd) ? s.delete(lawd) : s.add(lawd); applySel(s);
  }
  const allLawds = () => (meta.rankings || []).map((r) => r.lawd_cd);
  function selectAllToggle() {
    const all = allLawds();
    applySel(getSel().size >= all.length ? new Set() : new Set(all));
  }
  // 선택 변경 시 랭킹·추이를 다시 그린다(차트/표만, 지도는 app.js가 처리)
  function refresh() { renderRankTable(); renderTrendControls(); renderTrend(); }

  function chip(text, on) {
    const b = document.createElement("button");
    b.className = "d-chip" + (on ? " on" : "");
    b.textContent = text;
    return b;
  }

  // ── 1) 구별 랭킹(클릭=구 선택, 복수) ────────────────────────────────
  function renderRankTable() {
    const ranks = meta.rankings || [];
    const sel = getSel();
    const allOn = sel.size > 0 && sel.size >= ranks.length;
    let html = `<div class="sel-bar">
      <button class="d-chip sel-all${allOn ? " on" : ""}">${allOn ? "전체 해제" : "전체 선택"}</button>
      <span class="sel-hint">행 클릭 = 구 선택(복수) · 지도·추이 연동</span></div>`;
    html += `<table class="rank-table"><thead><tr>
      <th>#</th><th>자치구</th><th>평단가</th><th>6개월</th><th>거래</th>
      </tr></thead><tbody>`;
    ranks.forEach((r, i) => {
      const chg = r.change_6m;
      const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
      html += `<tr data-lawd="${r.lawd_cd}" class="${sel.has(r.lawd_cd) ? "sel" : ""}">
        <td>${i + 1}</td><td>${r.name}</td>
        <td>${r.ppy_median ? Math.round(r.ppy_median).toLocaleString() : "-"}</td>
        <td class="${cls}">${chg != null ? (chg > 0 ? "+" : "") + chg + "%" : "-"}</td>
        <td>${(r.sale_count || 0).toLocaleString()}</td></tr>`;
    });
    const wrap = $("rank-table-wrap");
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelector(".sel-all").addEventListener("click", selectAllToggle);
    wrap.querySelectorAll("tr[data-lawd]").forEach((tr) =>
      tr.addEventListener("click", () => toggleSel(tr.dataset.lawd)));
    $("rank-desc").textContent = `기준: ${meta.last_updated_display || "-"} · 만원/평`;
  }

  // ── 2) 평단가 추이(선택 구 연동, 미선택 시 상위5 미리보기) ──────────
  function renderTrendControls() {
    const ranks = meta.rankings || [];
    const sel = getSel();
    const allOn = sel.size > 0 && sel.size >= ranks.length;
    const wrap = $("trend-chips");
    wrap.innerHTML = "";
    const all = chip(allOn ? "전체 해제" : "전체 선택", allOn);
    all.classList.add("sel-all");
    all.addEventListener("click", selectAllToggle);
    wrap.appendChild(all);
    ranks.forEach((r) => {
      const b = chip(r.name, sel.has(r.lawd_cd));
      b.addEventListener("click", () => toggleSel(r.lawd_cd));
      wrap.appendChild(b);
    });
  }

  function renderTrend() {
    if (!dash || !dash.ppy_trend) return;
    const names = {};
    (meta.rankings || []).forEach((r) => { names[r.lawd_cd] = r.name; });
    const sel = getSel();
    const list = sel.size ? [...sel]
      : (meta.rankings || []).slice(0, 5).map((r) => r.lawd_cd);   // 미선택 미리보기
    const months = new Set();
    list.forEach((cd) => (dash.ppy_trend[cd] || []).forEach((p) => months.add(p.m)));
    const labels = [...months].sort();
    const datasets = list.map((cd, i) => {
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
    let html = `<div class="sel-hint">단지 클릭 = 지도에 표시</div>
      <table class="rank-table"><thead><tr>
      <th>단지</th><th>법정동</th><th>준공</th><th>연차</th><th>세대수</th>
      <th>매매중앙값</th><th>평단가</th></tr></thead><tbody>`;
    const nowY = new Date().getFullYear();
    list.forEach((c) => {
      html += `<tr data-id="${c.id}"><td>${c.apt}</td><td>${c.umd || "-"}</td>
        <td>${c.build_year}</td><td>${nowY - c.build_year}년</td>
        <td>${c.households ? c.households.toLocaleString() : "-"}</td>
        <td>${SeoulCharts.fmt(c.sale_median)}</td>
        <td>${c.ppy_median ? Math.round(c.ppy_median).toLocaleString() : "-"}</td></tr>`;
    });
    const wrap = $("no-table-wrap");
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => {
        if (window.SeoulMap) window.SeoulMap.focusComplex(+tr.dataset.id);
      }));
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
    // period(월) 합집합을 라벨로 → 지표별 시작 시점이 달라도 정확히 정렬
    // (매매 2006~, 전세 2014~ 처럼 길이가 다르면 인덱스 정렬 시 어긋남)
    const seoulByStat = {};
    const monthSet = new Set();
    stats.forEach((stat) => {
      const regions = rebData[stat];
      const seoul = regions["서울"] || regions[Object.keys(regions)[0]] || [];
      seoulByStat[stat] = seoul;
      seoul.forEach((p) => monthSet.add(p.period));
    });
    const labels = [...monthSet].sort();
    const datasets = stats.map((stat, i) => {
      const map = {};
      seoulByStat[stat].forEach((p) => { map[p.period] = p.value; });
      return { label: stat, color: colors[i % colors.length],
        data: labels.map((m) => (m in map ? map[m] : null)) };
    });
    SeoulCharts.line("reb-chart", labels, datasets);
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });  // 매일 갱신 데이터 → 항상 최신
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
})();
