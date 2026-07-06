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
    renderSubs();
    renderMarketPhase();
    return true;
  }

  // 지도 페이지의 분할 패널에서 호출: 최초 1회 데이터 로드 + 차트 크기 재계산
  window.SeoulDash = {
    open: async () => {
      const ok = await init();
      if (ok) setTimeout(() => { renderTrend(); renderPeakShare(); renderRebChart(); }, 60);
    },
    refresh: () => { if (inited) renderRankTable(); },   // 관심구 별표 갱신
  };

  const favDistricts = () => {
    try { return new Set(JSON.parse(localStorage.getItem("seoul_apt_fav_districts") || "[]")); }
    catch { return new Set(); }
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
    const fav = favDistricts();
    ranks.forEach((r, i) => {
      const chg = r.change_6m;
      const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
      const star = fav.has(r.lawd_cd) ? '<span class="fav-star">★</span> ' : "";
      html += `<tr data-lawd="${r.lawd_cd}" class="${sel.has(r.lawd_cd) ? "sel" : ""}">
        <td>${i + 1}</td><td>${star}${r.name}</td>
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

  // ── 3) 신축↔구축 (전체 카테고리 + 정렬 토글) ────────────────────────
  let noLawd = "", noOrder = "new";   // ""=전체 · new=신축순 / old=구축순
  const noCache = {};                 // lawd_cd → 단지 목록(구별 캐시)
  const NO_CAP = 300;                 // '전체'일 때 표 렌더 상한

  function initNewOld() {
    const sel = $("no-district");
    sel.innerHTML = '<option value="">전체</option>';
    (meta.districts || []).forEach((d) => {
      const o = document.createElement("option");
      o.value = d.lawd_cd; o.textContent = d.name;
      sel.appendChild(o);
    });
    sel.value = noLawd;
    sel.addEventListener("change", () => { noLawd = sel.value; renderNewOld(); });
    renderNewOld();
  }

  async function loadDistrictComplexes(lawd) {
    if (noCache[lawd]) return noCache[lawd];
    const name = (meta.districts || []).find((d) => d.lawd_cd === lawd)?.name || "";
    const d = await fetchJSON(`${DATA}districts/${lawd}.json`);
    const list = (d.complexes || []).filter((c) => c.build_year)
      .map((c) => ({ ...c, gu: name }));
    noCache[lawd] = list;
    return list;
  }

  async function renderNewOld() {
    const wrap = $("no-table-wrap");
    wrap.innerHTML = '<div class="empty">불러오는 중…</div>';
    let list = [];
    try {
      if (noLawd) list = await loadDistrictComplexes(noLawd);
      else {
        const all = await Promise.all((meta.districts || [])
          .map((d) => loadDistrictComplexes(d.lawd_cd).catch(() => [])));
        list = all.flat();
      }
    } catch { wrap.innerHTML = '<div class="empty">데이터 없음</div>'; return; }

    list = list.slice().sort((a, b) =>
      noOrder === "new" ? b.build_year - a.build_year : a.build_year - b.build_year);
    const total = list.length;
    const rows = total > NO_CAP ? list.slice(0, NO_CAP) : list;
    const showGu = !noLawd;
    const nowY = new Date().getFullYear();

    let html = `<div class="sel-bar">
      <button class="d-chip${noOrder === "new" ? " on" : ""}" data-order="new">신축순</button>
      <button class="d-chip${noOrder === "old" ? " on" : ""}" data-order="old">구축순</button>
      <span class="sel-hint">단지 클릭 = 지도에 표시${total > NO_CAP ? ` · 상위 ${NO_CAP}/${total.toLocaleString()}` : ""}</span>
      </div>
      <table class="rank-table"><thead><tr>
      <th>단지</th>${showGu ? "<th>자치구</th>" : ""}<th>법정동</th><th>준공</th><th>연차</th>
      <th>세대수</th><th>매매중앙값</th><th>평단가</th></tr></thead><tbody>`;
    rows.forEach((c) => {
      html += `<tr data-id="${c.id}"><td>${c.apt}</td>${showGu ? `<td>${c.gu}</td>` : ""}
        <td>${c.umd || "-"}</td><td>${c.build_year}</td><td>${nowY - c.build_year}년</td>
        <td>${c.households ? c.households.toLocaleString() : "-"}</td>
        <td>${SeoulCharts.fmt(c.sale_median)}</td>
        <td>${c.ppy_median ? Math.round(c.ppy_median).toLocaleString() : "-"}</td></tr>`;
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("[data-order]").forEach((b) =>
      b.addEventListener("click", () => { noOrder = b.dataset.order; renderNewOld(); }));
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

  // ── 5b) 시장 국면 신호등 ────────────────────────────────────────────
  const PHASE_LABEL = { boom: "과열", recovery: "회복", slowdown: "둔화",
                        recession: "침체", neutral: "중립" };
  function renderMarketPhase() {
    const grid = $("phase-grid");
    if (!grid || !dash || !dash.market_phase) return;
    // 국면 정렬: 과열>둔화>중립>회복>침체 대략 강→약
    const order = { boom: 0, slowdown: 1, neutral: 2, recovery: 3, recession: 4 };
    const rows = dash.market_phase.slice()
      .sort((a, b) => order[a.phase] - order[b.phase]);
    grid.innerHTML = rows.map((r) => {
      const prc = r.price_chg != null
        ? `${r.price_chg > 0 ? "+" : ""}${r.price_chg}%` : "-";
      return `<div class="phase-cell ${r.phase}" data-lawd="${r.lawd_cd}"
        title="거래량 최근3개월/직전12개월 ${r.vol_ratio ?? "-"}배 · 가격 6개월 ${prc}">
        <div class="pc-gu">${r.name}</div>
        <div class="pc-label">${PHASE_LABEL[r.phase]}</div>
        <div class="pc-sub">${prc}</div></div>`;
    }).join("");
    grid.querySelectorAll(".phase-cell").forEach((c) =>
      c.addEventListener("click", () => toggleSel(c.dataset.lawd)));
  }

  // ── 6) 청약·분양 (서울) ─────────────────────────────────────────────
  function subStatus(it) {
    const d = new Date();
    const t = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (it.rcept_bgn && t < it.rcept_bgn) return { k: "upcoming", label: "예정" };
    if (it.rcept_end && t <= it.rcept_end) return { k: "open", label: "접수중" };
    if (it.przwner && t < it.przwner) return { k: "wait", label: "발표대기" };
    return { k: "done", label: "완료" };
  }

  async function renderSubs() {
    const wrap = $("subs-table-wrap"), cwrap = $("subs-cmpet-wrap");
    if (!wrap) return;
    let items = [];
    try { items = (await fetchJSON(DATA + "subscription.json")).items || []; }
    catch { wrap.innerHTML = '<div class="empty">청약 데이터 없음</div>'; return; }

    // 진행중·예정 목록(접수 시작일 오름차순)
    const active = items.filter((it) => ["upcoming", "open", "wait"].includes(subStatus(it).k))
      .sort((a, b) => (a.rcept_bgn || "9999") < (b.rcept_bgn || "9999") ? -1 : 1);
    if (!active.length) {
      wrap.innerHTML = '<div class="empty">진행중·예정 청약 없음</div>';
    } else {
      let html = `<table class="rank-table"><thead><tr>
        <th>상태</th><th>주택명</th><th>구</th><th>세대</th><th>접수기간</th><th>최고분양가</th><th>안전마진</th>
        </tr></thead><tbody>`;
      active.forEach((it) => {
        const st = subStatus(it);
        const top = Math.max(0, ...(it.models || []).map((m) => m.price || 0));
        const mgns = (it.models || []).filter((m) => m.mgn != null).map((m) => m.mgn);
        const bm = mgns.length ? Math.max(...mgns) : null;
        const mgnTxt = bm == null ? "-"
          : `<span class="mgn ${bm > 0 ? "pos" : "neg"}">${bm > 0 ? "+" : ""}${bm}%</span>`;
        html += `<tr data-lat="${it.lat || ""}" data-lon="${it.lon || ""}">
          <td><span class="badge sub-badge-${st.k}">${st.label}</span></td>
          <td>${it.name}${it.kind === "remndr" ? ' <span class="sel-hint">(무순위)</span>' : ""}</td>
          <td>${it.gu || "-"}</td><td>${it.tot ? it.tot.toLocaleString() : "-"}</td>
          <td>${it.rcept_bgn || "-"} ~ ${it.rcept_end || "-"}</td>
          <td>${top ? SeoulCharts.fmt(top) : "-"}</td><td>${mgnTxt}</td></tr>`;
      });
      wrap.innerHTML = html + "</tbody></table>";
      wrap.querySelectorAll("tr[data-lat]").forEach((tr) =>
        tr.addEventListener("click", () => {
          if (window.SeoulMap && tr.dataset.lat) {
            window.SeoulMap.focusLatLng(+tr.dataset.lat, +tr.dataset.lon);
          }
        }));
    }

    // 최근 마감 경쟁률 상위(주택형 최고 경쟁률 기준)
    if (!cwrap) return;
    const rated = items
      .map((it) => {
        const best = Math.max(0, ...(it.cmpet || [])
          .map((c) => parseFloat(c.rate) || 0));
        return { it, best };
      })
      .filter((x) => x.best > 0)
      .sort((a, b) => b.best - a.best)
      .slice(0, 15);
    if (!rated.length) {
      cwrap.innerHTML = '<div class="empty">경쟁률 데이터 없음</div>';
      return;
    }
    let ch = `<table class="rank-table"><thead><tr>
      <th>주택명</th><th>구</th><th>접수마감</th><th>최고 경쟁률</th>
      </tr></thead><tbody>`;
    rated.forEach(({ it, best }) => {
      ch += `<tr><td>${it.name}</td><td>${it.gu || "-"}</td>
        <td>${it.rcept_end || "-"}</td><td>${best.toLocaleString()} : 1</td></tr>`;
    });
    cwrap.innerHTML = ch + "</tbody></table>";
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });  // 매일 갱신 데이터 → 항상 최신
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
})();
