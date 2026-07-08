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
    renderScreeners();
    renderBargains();
    renderValuation();
    renderCompare();
    return true;
  }

  // 지도 페이지의 분할 패널에서 호출: 최초 1회 데이터 로드 + 차트 크기 재계산
  window.SeoulDash = {
    open: async () => {
      const ok = await init();
      if (ok) setTimeout(() => {
        renderTrend(); renderPeakShare(); renderRebChart();  // renderRebChart가 시장심리도 그림
      }, 60);
    },
    // 매수 후보 패널(밸류에이션 + 단지 비교) 열릴 때 차트 크기 재계산
    openBuy: async () => {
      const ok = await init();
      if (ok) setTimeout(() => {
        if (valData) renderValScatter();
        if (mkAll && cmpIds.length) renderCmpBody();
      }, 60);
    },
    refresh: () => { if (inited) {                       // 관심구 별표 갱신
      renderRankTable(); renderMarketPhase();
      if (valData) renderValAll();
    } },
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
    // 가격지수 2종만(수급·외지인·미분양은 스케일이 달라 별도 섹션)
    const stats = ["아파트 매매가격지수", "아파트 전세가격지수"]
      .filter((s) => rebData[s]);
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
    renderMarketStats();
  }

  // ── 5a) 시장 심리 지표(수급·외지인·미분양) ──────────────────────────
  function _line(canvasId, series, label, color) {
    if (!document.getElementById(canvasId) || !series || !series.length) return;
    const labels = series.map((p) => p.period);
    SeoulCharts.line(canvasId, labels,
      [{ label, color, data: series.map((p) => p.value) }]);
  }
  function renderMarketStats() {
    if (!rebData || !window.SeoulCharts) return;
    const S = rebData["아파트 매매수급지수"], O = rebData["외지인 매수비중(%)"],
          U = rebData["미분양(호)"];
    if (S) _line("ms-supply", S["서울"], "매매수급지수", "#7c3aed");
    if (O) {
      _line("ms-outsider", O["서울"], "외지인 매수비중", "#ea580c");
      const seoul = O["서울"] || [];
      if (seoul.length && $("ms-out-latest"))
        $("ms-out-latest").textContent =
          `서울 ${seoul[seoul.length - 1].value}% (${seoul[seoul.length - 1].period})`;
      // 구별 최신 바(구 이름 = SEOUL_DISTRICTS 값)
      const guVals = (meta.districts || []).map((d) => {
        const arr = O[d.name] || [];
        return arr.length ? { name: d.name, v: arr[arr.length - 1].value } : null;
      }).filter(Boolean).sort((a, b) => b.v - a.v);
      if (guVals.length)
        SeoulCharts.bar("ms-out-bar", guVals.map((g) => g.name),
          guVals.map((g) => g.v),
          { horizontal: true, label: "외지인 비중", unit: "%", color: "#ea580c" });
    }
    if (U) {
      const s = U["서울>계"] || U["서울"] || [];
      _line("ms-unsold", s, "미분양(호)", "#64748b");
      if (s.length && $("ms-unsold-latest"))
        $("ms-unsold-latest").textContent =
          `서울 ${Math.round(s[s.length - 1].value).toLocaleString()}호 (${s[s.length - 1].period})`;
    }
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
    const fav = favDistricts();
    grid.innerHTML = rows.map((r) => {
      const prc = r.price_chg != null
        ? `${r.price_chg > 0 ? "+" : ""}${r.price_chg}%` : "-";
      const star = fav.has(r.lawd_cd) ? '<span class="fav-star">★</span> ' : "";
      return `<div class="phase-cell ${r.phase}" data-lawd="${r.lawd_cd}"
        title="거래량 최근3개월/직전12개월 ${r.vol_ratio ?? "-"}배 · 가격 6개월 ${prc}">
        <div class="pc-gu">${star}${r.name}</div>
        <div class="pc-label">${PHASE_LABEL[r.phase]}</div>
        <div class="pc-sub">${prc}</div></div>`;
    }).join("");
    grid.querySelectorAll(".phase-cell").forEach((c) =>
      c.addEventListener("click", () => toggleSel(c.dataset.lawd)));
  }

  // ── 5c) 스크리너(재건축 후보 · 유동성) ──────────────────────────────
  const GU_NAME = {};
  async function renderScreeners() {
    (meta.districts || []).forEach((d) => { GU_NAME[d.lawd_cd] = d.name; });
    let mk = [];
    try { mk = (await fetchJSON(DATA + "markers.json")).markers || []; }
    catch { return; }
    const nowY = new Date().getFullYear();
    const focus = (id) => { if (window.SeoulMap) window.SeoulMap.focusComplex(id); };

    // 재건축 후보: 연차 30+ · 용적률 50~200% · 150세대+. 용적률 낮고 오래될수록 상위.
    // (용적률 50% 미만·소규모는 건축물대장 오류/비아파트라 제외)
    const redev = mk.filter((m) => m.by && m.far != null && m.hh
        && (nowY - m.by) >= 30 && m.far >= 50 && m.far < 200 && m.hh >= 150)
      .sort((a, b) => (a.far - b.far) || (a.by - b.by)).slice(0, 40);
    const rWrap = $("redev-wrap");
    if (rWrap) {
      if (redev.length) {
        rWrap.innerHTML = screenerTable(redev, [
          ["단지", (m) => m.apt], ["구", (m) => GU_NAME[m.lawd_cd] || "-"],
          ["준공", (m) => m.by], ["연차", (m) => (nowY - m.by) + "년"],
          ["용적률", (m) => m.far + "%"], ["세대", (m) => m.hh.toLocaleString()],
          ["평단가", (m) => m.ppy ? Math.round(m.ppy).toLocaleString() : "-"],
        ]);
        bindRows(rWrap, focus);
      } else {
        rWrap.innerHTML = '<div class="empty">건축물대장 수집분에 조건 충족 단지 없음</div>';
      }
    }
    const withFar = mk.filter((m) => m.far != null).length;
    if ($("redev-desc")) $("redev-desc").textContent =
      `연차 30년+ · 용적률 200% 미만 · 용적률 낮은 순 (건축물대장 수집 ${withFar.toLocaleString()}개 단지 대상)`;

    // 유동성: 연간 거래 ÷ 세대수 회전율(%). 세대수·최근1년거래 보유 단지.
    const liq = mk.filter((m) => m.hh && m.hh >= 100 && m.n1y != null)
      .map((m) => ({ ...m, turn: +(m.n1y / m.hh * 100).toFixed(1) }))
      .sort((a, b) => b.turn - a.turn).slice(0, 40);
    const lWrap = $("liq-wrap");
    if (lWrap) {
      if (liq.length) {
        lWrap.innerHTML = screenerTable(liq, [
          ["단지", (m) => m.apt], ["구", (m) => GU_NAME[m.lawd_cd] || "-"],
          ["세대", (m) => m.hh.toLocaleString()], ["1년거래", (m) => m.n1y],
          ["회전율", (m) => `<b>${m.turn}%</b>`],
          ["평단가", (m) => m.ppy ? Math.round(m.ppy).toLocaleString() : "-"],
        ]);
        bindRows(lWrap, focus);
      } else {
        lWrap.innerHTML = '<div class="empty">데이터 없음</div>';
      }
    }
  }

  function screenerTable(rows, cols) {
    return `<table class="rank-table"><thead><tr>${
      cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>`
      + rows.map((m) => `<tr data-id="${m.id}">${
          cols.map((c) => `<td>${c[1](m)}</td>`).join("")}</tr>`).join("")
      + "</tbody></table>";
  }
  function bindRows(wrap, onClick) {
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => onClick(+tr.dataset.id)));
  }

  // ── 5d) 급매 포착 ───────────────────────────────────────────────────
  function renderBargains() {
    const wrap = $("bargain-wrap");
    if (!wrap || !dash) return;
    const list = dash.bargains || [];
    if ($("bargain-days")) $("bargain-days").textContent =
      `(최근 ${dash.bargains_days || 45}일 · ${list.length}건)`;
    if (!list.length) {
      wrap.innerHTML = '<div class="empty">최근 급매 없음</div>';
      return;
    }
    const guName = (cd) => (meta.districts || [])
      .find((d) => d.lawd_cd === cd)?.name || cd;
    let html = `<table class="rank-table"><thead><tr>
      <th>구</th><th>단지</th><th>면적</th><th>층</th><th>거래가</th>
      <th>중앙값</th><th>할인</th><th>계약일</th></tr></thead><tbody>`;
    list.forEach((b) => {
      html += `<tr data-id="${b.id}">
        <td>${guName(b.lawd_cd)}</td><td>${b.apt}</td>
        <td>${b.area}㎡</td><td>${b.floor || "-"}</td>
        <td>${SeoulCharts.fmt(b.amount)}</td><td>${SeoulCharts.fmt(b.med)}</td>
        <td><span class="mgn neg">${b.disc}%</span></td>
        <td>${b.date}</td></tr>`;
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => {
        if (window.SeoulMap) window.SeoulMap.focusComplex(+tr.dataset.id);
      }));
  }

  // ── 5e) 밸류에이션 종합(평형대 × 히트맵 + 판정별 리스트 + 산점도) ─────
  const VAL_VERDICT = [
    ["cheap", "저평가", (p) => p <= 30, "#059669"],
    ["mid", "중단", (p) => p > 30 && p < 80, "#d97706"],
    ["hot", "고점근접", (p) => p >= 80, "#ef4444"],
  ];
  const VAL_M2 = 3.305785;   // 1평 = 3.305785㎡
  const VAL_BUCKETS = [["~60㎡", 0, 60], ["60~85㎡", 60, 85],
                       ["85~135㎡", 85, 135], ["135㎡~", 135, 99999]];
  let valData = null, valGu = "", valKind = "cheap";
  let valArea = { lo: 0, hi: 80 };   // 평형대(평), 0~80 전체

  // 선택 평형대에 해당하는 버킷 밸류에이션(전체 범위면 all). 없으면 null.
  function valView(it) {
    let v, b = "all";
    if (valArea.lo <= 0 && valArea.hi >= 80) {
      v = it.all;
    } else {
      const lo = valArea.lo * VAL_M2, hi = valArea.hi * VAL_M2;
      let best = null, bestOv = 0, bestB = null;
      for (const [bl, blo, bhi] of VAL_BUCKETS) {
        const x = it.areas[bl];
        if (!x) continue;
        const ov = Math.min(hi, bhi) - Math.max(lo, blo);
        if (ov > bestOv) { bestOv = ov; best = x; bestB = bl; }
      }
      v = bestOv > 0 ? best : null; b = bestB;
    }
    return v ? { id: it.id, apt: it.apt, lawd: it.lawd, b,
                 pos: v.pos, vp: v.vp, jr: v.jr, ppy: v.ppy, m: v.m } : null;
  }
  // 마커에서 평(대표/선택 버킷)·세대수 조회
  let valMkById = null;
  function valPy(view) {
    const mk = valMkById && valMkById[view.id];
    if (!mk || !mk.sale_area) return null;
    const bucket = view.b === "all" ? mk.rep : view.b;
    const o = bucket ? mk.sale_area[bucket] : null;
    return o ? o.py : null;
  }
  function valHh(view) {
    const mk = valMkById && valMkById[view.id];
    return mk ? mk.hh : null;
  }
  function valViews() { return valData.items.map(valView).filter(Boolean); }

  function valGuSummary(views) {
    const by = {};
    views.forEach((x) => { (by[x.lawd] = by[x.lawd] || []).push(x.pos); });
    return Object.entries(by).map(([lawd, poss]) => ({
      lawd_cd: lawd, name: GU_NAME[lawd] || lawd, n: poss.length,
      avg_pos: Math.round(poss.reduce((a, b) => a + b, 0) / poss.length),
      cheap: poss.filter((p) => p <= 30).length,
      mid: poss.filter((p) => p > 30 && p < 80).length,
      hot: poss.filter((p) => p >= 80).length,
    })).sort((a, b) => a.avg_pos - b.avg_pos);
  }

  async function renderValuation() {
    if (!$("val-grid")) return;
    (meta.districts || []).forEach((d) => { GU_NAME[d.lawd_cd] = d.name; });
    if (!valData) {
      try { valData = await fetchJSON(DATA + "valuation.json"); }
      catch { $("val-grid").innerHTML = '<div class="empty">밸류에이션 데이터 없음</div>'; return; }
    }
    await loadMk();                       // 평·세대수 표기용
    if (!valMkById) { valMkById = {}; mkAll.forEach((m) => { valMkById[m.id] = m; }); }
    bindValArea();
    renderValAll();
  }
  function renderValAll() {
    const views = valViews();
    if ($("val-meta")) $("val-meta").textContent =
      `(선택 평형대 ${views.length.toLocaleString()}개 단지)`;
    renderValGrid(views);
    renderValList(views);
    renderValScatter(views);
  }

  // 평형대 듀얼레인지 슬라이더
  function paintValArea() {
    const { lo, hi } = valArea, pc = (v) => v / 80 * 100;
    const fill = $("va-fill");
    if (fill) { fill.style.left = pc(lo) + "%"; fill.style.width = (pc(hi) - pc(lo)) + "%"; }
    const val = $("va-val");
    if (val) val.textContent = (lo <= 0 && hi >= 80) ? "전체"
      : `${lo}평 ~ ${hi}평${hi >= 80 ? "↑" : ""}`;
  }
  function bindValArea() {
    const lo = $("va-lo"), hi = $("va-hi");
    if (!lo || lo._bound) { paintValArea(); return; }
    lo._bound = true;
    $("va-ticks").innerHTML = [[0, "0"], [20, "20"], [40, "40"], [60, "60"], [80, "80+"]]
      .map(([v, t]) => { const p = v / 80 * 100, tx = p <= 0 ? "0" : p >= 100 ? "-100%" : "-50%";
        return `<span style="left:${p}%;transform:translateX(${tx})">${t}</span>`; }).join("");
    const upd = (commit) => {
      let a = +lo.value, b = +hi.value;
      if (a > b) { if (document.activeElement === lo) { b = a; hi.value = b; } else { a = b; lo.value = a; } }
      valArea = { lo: a, hi: b }; paintValArea();
      if (commit) renderValAll();
    };
    lo.addEventListener("input", () => upd(false));
    hi.addEventListener("input", () => upd(false));
    lo.addEventListener("change", () => upd(true));
    hi.addEventListener("change", () => upd(true));
    paintValArea();
  }

  const VAL_COLORS = ["#059669", "#65a30d", "#d97706", "#ea580c", "#ef4444"];
  function valColor(p, lo, hi) {   // 구간 내 상대값 5단계(전체 고점권이어도 대비 유지)
    const t = hi > lo ? (p - lo) / (hi - lo) : 0.5;
    return VAL_COLORS[Math.min(4, Math.floor(t * 5))];
  }

  function renderValGrid(views) {
    const grid = $("val-grid"), fav = favDistricts();
    const gu = valGuSummary(views);
    if (!gu.length) { grid.innerHTML = '<div class="empty">해당 평형대 데이터 없음</div>'; return; }
    const poss = gu.map((g) => g.avg_pos), lo = Math.min(...poss), hi = Math.max(...poss);
    grid.innerHTML = gu.map((g) => {
      const star = fav.has(g.lawd_cd) ? '<span class="fav-star">★</span> ' : "";
      const on = valGu === g.lawd_cd ? " on" : "";
      return `<div class="phase-cell val-cell${on}" data-lawd="${g.lawd_cd}"
        style="background:${valColor(g.avg_pos, lo, hi)}"
        title="평균 5년위치 ${g.avg_pos}% · 저평가 ${g.cheap} / 중단 ${g.mid} / 고점근접 ${g.hot}">
        <div class="pc-gu">${star}${g.name}</div>
        <div class="pc-label">${g.avg_pos}%</div>
        <div class="pc-sub">저평가 ${g.cheap}</div></div>`;
    }).join("");
    grid.querySelectorAll(".val-cell").forEach((c) =>
      c.addEventListener("click", () => {
        valGu = valGu === c.dataset.lawd ? "" : c.dataset.lawd;   // 재클릭=해제
        renderValAll();
      }));
  }

  function renderValList(views) {
    const chips = $("val-chips"), wrap = $("val-list-wrap");
    const kind = VAL_VERDICT.find((v) => v[0] === valKind);
    chips.innerHTML = VAL_VERDICT.map(([k, label]) =>
      `<button class="d-chip${valKind === k ? " on" : ""}" data-kind="${k}">${label}</button>`).join("")
      + `<button class="d-chip${valKind === "" ? " on" : ""}" data-kind="">전체</button>`
      + (valGu ? ` <button class="d-chip on" data-clear-gu="1">${GU_NAME[valGu] || valGu} ✕</button>` : "");
    chips.querySelectorAll("[data-kind]").forEach((b) =>
      b.addEventListener("click", () => { valKind = b.dataset.kind; renderValAll(); }));
    const clear = chips.querySelector("[data-clear-gu]");
    if (clear) clear.addEventListener("click", () => { valGu = ""; renderValAll(); });

    const rows = views.filter((v) => (!valGu || v.lawd === valGu)
      && (!kind || kind[2](v.pos))).sort((a, b) => a.pos - b.pos);
    if (!rows.length) { wrap.innerHTML = '<div class="empty">조건에 맞는 단지 없음</div>'; return; }
    const CAP = 100, shown = rows.slice(0, CAP);
    let html = `<div class="sel-hint" style="margin:4px 0 6px">${rows.length.toLocaleString()}건${rows.length > CAP ? ` 중 상위 ${CAP}` : ""} · 5년위치 낮은 순 · 행 클릭=지도</div>
      <table class="rank-table"><thead><tr>
      <th>단지</th><th>구</th><th>평</th><th>세대</th><th>평단가</th><th>5년위치</th><th>고점대비</th><th>전세가율</th><th>표본</th>
      </tr></thead><tbody>`;
    shown.forEach((it) => {
      const shield = (it.pos <= 30 && it.jr != null && it.jr >= 60)
        ? ' <span title="전세가율 높음 - 하방 견고">🛡️</span>' : "";
      const py = valPy(it), hh = valHh(it);
      html += `<tr data-id="${it.id}">
        <td>${it.apt}${shield}</td><td>${GU_NAME[it.lawd] || "-"}</td>
        <td>${py != null ? py + "평" : "-"}</td>
        <td>${hh != null ? hh.toLocaleString() : "-"}</td>
        <td>${it.ppy.toLocaleString()}</td><td><b>${it.pos}%</b></td>
        <td>${it.vp != null ? it.vp + "%" : "-"}</td>
        <td>${it.jr != null ? it.jr + "%" : "-"}</td>
        <td>${it.m}개월</td></tr>`;
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => {
        if (window.SeoulMap) window.SeoulMap.focusComplex(+tr.dataset.id);
      }));
  }

  function renderValScatter(views) {
    if (!document.getElementById("val-scatter") || !window.SeoulCharts) return;
    const inView = (views || valViews()).filter((v) => !valGu || v.lawd === valGu);
    const base = inView.filter((v) => v.jr != null);
    // 전세가율 없는 단지는 Y축(전세가율)에 올릴 수 없어 산점도에서 제외됨을 명시
    const excluded = inView.length - base.length;
    if ($("val-scatter-note")) $("val-scatter-note").textContent =
      `· 전세가율 있는 ${base.length.toLocaleString()}개 표시`
      + (excluded ? ` (전세가율 미집계 ${excluded.toLocaleString()}개 제외)` : "");
    const datasets = VAL_VERDICT.map(([k, label, test, color]) => ({
      label, color,
      data: base.filter((v) => test(v.pos)).map((v) => ({ x: v.pos, y: v.jr, meta: v })),
    }));
    SeoulCharts.scatter("val-scatter", datasets, {
      xLabel: "5년 평단가 위치(%)", yLabel: "전세가율(%)",
      xMin: 0, xMax: 100, yMin: 0, xUnit: "%", yUnit: "%",
      onClick: (meta) => { if (window.SeoulMap) window.SeoulMap.focusComplex(meta.id); },
    });
  }

  // ── 5f) 단지 비교(중첩 추이 + 스펙 비교표) ──────────────────────────
  let cmpIds = [], mkAll = null;
  const cmpDetails = {};   // id -> complex detail JSON 캐시
  try { cmpIds = JSON.parse(localStorage.getItem("seoul_apt_compare") || "[]"); }
  catch { cmpIds = []; }
  const CMP_MAX = 5;

  async function loadMk() {
    if (!mkAll) mkAll = (await fetchJSON(DATA + "markers.json")).markers || [];
    return mkAll;
  }
  function saveCmp() {
    localStorage.setItem("seoul_apt_compare", JSON.stringify(cmpIds));
  }

  async function renderCompare() {
    if (!$("cmp-search")) return;
    (meta.districts || []).forEach((d) => { GU_NAME[d.lawd_cd] = d.name; });
    await loadMk();
    bindCmpBar();
    await renderCmpBody();
  }

  function bindCmpBar() {
    const inp = $("cmp-search");
    if (inp._bound) return;
    inp._bound = true;
    inp.addEventListener("input", () => {
      const q = inp.value.trim();
      if (q.length < 2 || q.includes("#")) return;
      const hits = mkAll.filter((m) => m.apt.includes(q)).slice(0, 20);
      $("cmp-datalist").innerHTML = hits.map((m) =>
        `<option value="${m.apt} · ${GU_NAME[m.lawd_cd] || m.lawd_cd} #${m.id}">`).join("");
    });
    inp.addEventListener("change", () => {
      const mch = inp.value.match(/#(\d+)$/);
      if (!mch) return;
      addCmp(+mch[1]);
      inp.value = "";
    });
    $("cmp-load-fav").addEventListener("click", () => {
      let favs = [];
      try { favs = JSON.parse(localStorage.getItem("seoul_apt_favs") || "[]"); }
      catch { favs = []; }
      favs.forEach((f) => { if (cmpIds.length < CMP_MAX && !cmpIds.includes(f.id)) cmpIds.push(f.id); });
      saveCmp(); renderCmpBody();
    });
    $("cmp-clear").addEventListener("click", () => {
      cmpIds = []; saveCmp(); renderCmpBody();
    });
  }

  function addCmp(id) {
    if (cmpIds.includes(id)) return;
    if (cmpIds.length >= CMP_MAX) { cmpIds.shift(); }   // 가장 오래된 것 제거
    cmpIds.push(id);
    saveCmp(); renderCmpBody();
  }

  async function cmpDetail(mk) {
    if (!cmpDetails[mk.id]) {
      try {
        cmpDetails[mk.id] = await fetchJSON(`${DATA}complex/${mk.lawd_cd}/${mk.id}.json`);
      } catch { cmpDetails[mk.id] = {}; }
    }
    return cmpDetails[mk.id];
  }

  async function renderCmpBody() {
    const chips = $("cmp-chips"), wrap = $("cmp-table-wrap");
    const mks = cmpIds.map((id) => mkAll.find((m) => m.id === id)).filter(Boolean);
    // 칩
    chips.innerHTML = mks.map((m, i) =>
      `<span class="cmp-chip" style="border-color:${COLORS[i % COLORS.length]}">
        <i style="background:${COLORS[i % COLORS.length]}"></i>${m.apt}
        <b data-del="${m.id}">✕</b></span>`).join("")
      || '<span class="sel-hint">단지를 검색해 추가하세요 (지도에서 관심단지 ★ 등록 후 불러오기도 가능)</span>';
    chips.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", () => {
        cmpIds = cmpIds.filter((x) => x !== +b.dataset.del);
        saveCmp(); renderCmpBody();
      }));
    if (!mks.length) {
      SeoulCharts.destroy("cmp-chart"); wrap.innerHTML = ""; return;
    }
    // 상세(추이·밸류) 로드
    const details = await Promise.all(mks.map(cmpDetail));
    // 중첩 차트: 월 라벨 union
    const monthSet = new Set();
    details.forEach((d) => (d.ppy_series || []).forEach((p) => monthSet.add(p.m)));
    const labels = [...monthSet].sort();
    const datasets = mks.map((m, i) => {
      const map = {};
      (details[i].ppy_series || []).forEach((p) => { map[p.m] = p.v; });
      return { label: m.apt, color: COLORS[i % COLORS.length],
               data: labels.map((x) => map[x] ?? null) };
    });
    SeoulCharts.line("cmp-chart", labels, datasets);
    // 스펙 비교표(행=항목, 열=단지)
    const nowY = new Date().getFullYear();
    const repPrice = (m) => {
      const o = m.rep && m.sale_area ? m.sale_area[m.rep] : null;
      return o ? `${SeoulCharts.fmt(o.p)}·${o.py}평` : "-";
    };
    const rows = [
      ["위치", (m, d) => `${GU_NAME[m.lawd_cd] || "-"} ${d.umd || ""}`],
      ["준공", (m) => m.by ? `${m.by} (${nowY - m.by}년)` : "-"],
      ["세대수", (m) => m.hh ? m.hh.toLocaleString() : "-"],
      ["용적률", (m) => m.far != null ? m.far + "%" : "-"],
      ["대표평형 최근매매", repPrice],
      ["평단가(만/평)", (m) => m.ppy ? Math.round(m.ppy).toLocaleString() : "-"],
      ["전세가율", (m) => m.jeonse_ratio != null ? m.jeonse_ratio + "%" : "-"],
      ["1년 거래(회전율)", (m) => m.n1y != null
        ? `${m.n1y}건${m.hh ? ` (${(m.n1y / m.hh * 100).toFixed(1)}%)` : ""}` : "-"],
      ["5년위치", (m, d) => d.valuation ? `<b>${d.valuation.pos}%</b>` : "-"],
      ["고점대비", (m, d) => d.valuation && d.valuation.vs_peak != null
        ? d.valuation.vs_peak + "%" : "-"],
    ];
    let html = `<table class="rank-table cmp-table"><thead><tr><th></th>`
      + mks.map((m, i) => `<th class="cmp-head" data-id="${m.id}">
          <i style="background:${COLORS[i % COLORS.length]}"></i>${m.apt}</th>`).join("")
      + "</tr></thead><tbody>";
    rows.forEach(([label, fn]) => {
      html += `<tr><td class="cmp-label">${label}</td>`
        + mks.map((m, i) => `<td>${fn(m, details[i])}</td>`).join("") + "</tr>";
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll(".cmp-head").forEach((th) =>
      th.addEventListener("click", () => {
        if (window.SeoulMap) window.SeoulMap.focusComplex(+th.dataset.id);
      }));
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
