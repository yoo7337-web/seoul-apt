/* 대시보드 - 랭킹·평단가 추이·신축정렬·신고가 비중 */
(function () {
  "use strict";
  const DATA = "data/";
  const $ = (id) => document.getElementById(id);
  // 공공데이터라 실위험은 낮지만 단지명·주택명을 innerHTML 로 넣으므로
  // app.js 와 동일하게 이스케이프해 둔다(판매 제품 기준 통일).
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
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
    renderSources();
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
    // 실구매 비용 계산 패널
    openCost: async () => {
      const ok = await init();
      if (ok) renderCost();
    },
    // 청약·분양 패널(목록·경쟁률). init 이 renderSubs 를 이미 호출하지만
    // 데이터 지연/실패 대비해 다시 렌더.
    openSubs: async () => {
      const ok = await init();
      if (ok) renderSubs();
    },
    // 종합점수 패널(입지·단지·가격·유동성 랭킹)
    openScore: async () => {
      const ok = await init();
      if (ok) renderScore();
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

  // ── 데이터 기준일(소스별 실제 기준일자) ─────────────────────────────
  function renderSources() {
    const wrap = $("src-table-wrap");
    if (!wrap) return;
    $("src-updated").textContent =
      `자동 갱신: 매일 09:00 KST · 마지막 처리 ${meta.last_updated_display || "-"}`;
    const rows = meta.sources || [];
    if (!rows.length) { wrap.innerHTML = '<div class="empty">기준일 정보 없음</div>'; return; }
    wrap.innerHTML = `<table class="rank-table"><thead><tr>
      <th>데이터</th><th>기준일</th><th>비고</th></tr></thead><tbody>${
      rows.map((s) => `<tr><td>${s.k}</td><td><b>${s.d}</b></td>
        <td style="color:var(--muted)">${s.note || ""}</td></tr>`).join("")
    }</tbody></table>`;
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
      html += `<tr data-id="${c.id}"><td>${esc(c.apt)}</td>${showGu ? `<td>${c.gu}</td>` : ""}
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
        <td>${guName(b.lawd_cd)}</td><td>${esc(b.apt)}</td>
        <td>${b.area}㎡</td><td>${b.floor || "-"}</td>
        <td>${SeoulCharts.fmt(b.amount)}</td><td>${SeoulCharts.fmt(b.med)}</td>
        <td><span class="mgn neg">${b.disc}%</span></td>
        <td>${b.date}</td></tr>`;
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => {
        // 급매 실거래의 실제 전용면적(㎡)으로 지도 상세/버블을 맞춘다(대표평형이
        // 다른 크기면 "이 급매"와 다른 가격이 보이는 불일치 방지)
        const b = list.find((x) => x.id === +tr.dataset.id);
        if (window.SeoulMap) window.SeoulMap.focusComplex(+tr.dataset.id, b ? b.area : undefined);
      }));
  }

  // ── 5e) 밸류에이션 종합(평형대 × 히트맵 + 판정별 리스트 + 산점도) ─────
  const VAL_VERDICT = [
    ["cheap", "저평가", (p) => p <= 30, "#059669"],
    ["mid", "중단", (p) => p > 30 && p < 80, "#d97706"],
    ["hot", "고점근접", (p) => p >= 80, "#ef4444"],
  ];
  // 평형대 = 전용면적 버킷 '정확 선택'(전체 or 특정 버킷). 연속 슬라이더는
  // ~60㎡·135㎡~ 같은 넓은/무한 버킷과 겹침 계산이 어긋나(4평이 18~26평에,
  // 41평이 60~80평에 걸림) 버킷 단위로 정확히 고르게 한다.
  const VAL_AREA_OPTS = [
    ["all", "전체"], ["~60㎡", "~18평"], ["60~85㎡", "18~26평"],
    ["85~135㎡", "26~41평"], ["135㎡~", "41평↑"],
  ];
  let valData = null, valGu = "", valKind = "cheap", valBucket = "all";
  let valProfileOn = false;   // 💼 '내 프로필만' 필터 상태

  // 선택 버킷의 밸류에이션(전체면 all). 그 버킷 데이터가 없으면 null(제외).
  function valView(it) {
    const v = valBucket === "all" ? it.all : it.areas[valBucket];
    return v ? { id: it.id, apt: it.apt, lawd: it.lawd, b: valBucket,
                 pos: v.pos, vp: v.vp, jr: v.jr, ppy: v.ppy, m: v.m } : null;
  }

  // 💼 매수 프로필(지도에서 저장한 필터 스냅샷) 조건에 맞는 단지만
  function valMatchProfile(view) {
    const p = window.SeoulMap && SeoulMap.getProfile && SeoulMap.getProfile();
    if (!p) return true;
    // 관심 구
    if (p.districts && p.districts.length && !p.districts.includes(view.lawd))
      return false;
    const mk = valMkById && valMkById[view.id];
    if (!mk) return false;
    // 예산(억): 프로필 가격범위가 설정돼 있으면 대표/선택 평형 최근매매가로 판정
    const pr = p.range && p.range.price;
    if (pr && (pr.lo > 0 || pr.hi < 40)) {
      const bucket = view.b === "all" ? mk.rep : view.b;
      const o = bucket && mk.sale_area ? mk.sale_area[bucket] : null;
      if (!o || !o.p) return false;
      const eok = o.p / 10000;
      if (pr.lo > 0 && eok < pr.lo) return false;
      if (pr.hi < 40 && eok > pr.hi) return false;
    }
    return true;   // 평형은 칩 토글 시 valBucket 자동 전환으로 반영(아래)
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
  // 현재 매물(매매) 건수 — export가 마커에 얹은 요약(ls). 미수집 단지는 null
  function valLs(view) {
    const mk = valMkById && valMkById[view.id];
    return mk && mk.ls != null ? mk.ls : null;
  }
  function valViews() {
    let views = valData.items.map(valView).filter(Boolean);
    if (valProfileOn) views = views.filter(valMatchProfile);
    return views;
  }

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
    renderValAreaChips();
    renderValAll();
  }
  function renderValAll() {
    renderValAreaChips();                 // 선택 버킷 활성 상태 반영
    const views = valViews();
    if ($("val-meta")) $("val-meta").textContent =
      `(선택 평형대 ${views.length.toLocaleString()}개 단지)`;
    renderValGrid(views);
    renderValList(views);
    renderValScatter(views);
  }

  // 평형대(전용면적 버킷) 선택 칩
  function renderValAreaChips() {
    const wrap = $("val-area-chips");
    if (!wrap) return;
    wrap.innerHTML = VAL_AREA_OPTS.map(([k, label]) =>
      `<button class="d-chip${valBucket === k ? " on" : ""}" data-bucket="${k}">${label}</button>`).join("");
    wrap.querySelectorAll("[data-bucket]").forEach((b) =>
      b.addEventListener("click", () => { valBucket = b.dataset.bucket; renderValAll(); }));
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
    const hasProfile = !!(window.SeoulMap && SeoulMap.getProfile && SeoulMap.getProfile());
    chips.innerHTML = VAL_VERDICT.map(([k, label]) =>
      `<button class="d-chip${valKind === k ? " on" : ""}" data-kind="${k}">${label}</button>`).join("")
      + `<button class="d-chip${valKind === "" ? " on" : ""}" data-kind="">전체</button>`
      + (hasProfile ? ` <button class="d-chip${valProfileOn ? " on" : ""}" data-profile="1"
          title="지도에서 저장한 매수 프로필(예산·구·평형)로 압축">💼 내 프로필만</button>` : "")
      + (valGu ? ` <button class="d-chip on" data-clear-gu="1">${GU_NAME[valGu] || valGu} ✕</button>` : "");
    chips.querySelectorAll("[data-kind]").forEach((b) =>
      b.addEventListener("click", () => { valKind = b.dataset.kind; renderValAll(); }));
    const profBtn = chips.querySelector("[data-profile]");
    if (profBtn) profBtn.addEventListener("click", () => {
      valProfileOn = !valProfileOn;
      if (valProfileOn) {
        const p = SeoulMap.getProfile();
        if (p && p.area) valBucket = p.area;   // 프로필 평형으로 자동 전환
      }
      renderValAll();
    });
    const clear = chips.querySelector("[data-clear-gu]");
    if (clear) clear.addEventListener("click", () => { valGu = ""; renderValAll(); });

    const rows = views.filter((v) => (!valGu || v.lawd === valGu)
      && (!kind || kind[2](v.pos))).sort((a, b) => a.pos - b.pos);
    if (!rows.length) { wrap.innerHTML = '<div class="empty">조건에 맞는 단지 없음</div>'; return; }
    const CAP = 100, shown = rows.slice(0, CAP);
    let html = `<div class="sel-hint" style="margin:4px 0 6px">${rows.length.toLocaleString()}건${rows.length > CAP ? ` 중 상위 ${CAP}` : ""} · 5년위치 낮은 순 · 행 클릭=지도</div>
      <table class="rank-table"><thead><tr>
      <th>단지</th><th>구</th><th>평</th><th>세대</th><th>5년위치</th><th>고점대비</th><th>전세가율</th><th>매물</th><th>표본</th>
      </tr></thead><tbody>`;
    shown.forEach((it) => {
      const shield = (it.pos <= 30 && it.jr != null && it.jr >= 60)
        ? ' <span title="전세가율 높음 - 하방 견고">🛡️</span>' : "";
      const py = valPy(it), hh = valHh(it), ls = valLs(it);
      html += `<tr data-id="${it.id}">
        <td>${it.apt}${shield}</td><td>${GU_NAME[it.lawd] || "-"}</td>
        <td>${py != null ? py + "평" : "-"}</td>
        <td>${hh != null ? hh.toLocaleString() : "-"}</td>
        <td><b>${it.pos}%</b></td>
        <td>${it.vp != null ? it.vp + "%" : "-"}</td>
        <td>${it.jr != null ? it.jr + "%" : "-"}</td>
        <td>${ls != null ? `<b>${ls}</b>건`
          : '<span title="매물 미수집 단지" style="color:var(--muted)">-</span>'}</td>
        <td>${it.m}개월</td></tr>`;
    });
    wrap.innerHTML = html + "</tbody></table>";
    wrap.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => {
        // 특정 평형 버킷(전체가 아니면) 그대로 지도 상세/버블에도 반영 -
        // 리스트가 "18~26평" 기준으로 보여준 값과 지도가 다른 평형(대표평형)을
        // 보여주는 불일치 방지(사고 이력)
        if (window.SeoulMap) window.SeoulMap.focusComplex(
          +tr.dataset.id, valBucket !== "all" ? valBucket : undefined);
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
        `<option value="${esc(m.apt)} · ${GU_NAME[m.lawd_cd] || m.lawd_cd} #${m.id}">`).join("");
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
    // 지도 가격 푯말 드래그 → 이 섹션에 드롭하면 비교 추가
    const dz = inp.closest("section");
    if (dz) {
      dz.addEventListener("dragover", (e) => {
        if ((e.dataTransfer.types || []).indexOf("text/plain") >= 0) {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          dz.classList.add("cmp-drop");
        }
      });
      dz.addEventListener("dragleave", (e) => {
        if (!dz.contains(e.relatedTarget)) dz.classList.remove("cmp-drop");
      });
      dz.addEventListener("drop", (e) => {
        const d = e.dataTransfer.getData("text/plain");
        dz.classList.remove("cmp-drop");
        if (d && d.indexOf("cmp:") === 0) { e.preventDefault(); addCmp(+d.slice(4)); }
      });
    }
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
        <i style="background:${COLORS[i % COLORS.length]}"></i>${esc(m.apt)}
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
          <i style="background:${COLORS[i % COLORS.length]}"></i>${esc(m.apt)}</th>`).join("")
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

  // ── 5g) 실구매 비용 계산(드래그로 단지 추가 → 필요현금 비교) ──────────
  const COST_BUCKET_ORDER = ["~60㎡", "60~85㎡", "85~135㎡", "135㎡~"];
  let costIds = [], costHomes = 1, costLtv = 40;
  const costPrice = {};    // id -> 사용자 편집 매수가(만원). 없으면 선택 평형 최근매매가
  const costBucket = {};   // id -> 선택 평형대(전용면적 버킷). 없으면 대표평형(rep)
  const COST_MAX = 5;
  try {
    const saved = JSON.parse(localStorage.getItem("seoul_apt_cost") || "{}");
    costIds = saved.ids || []; costHomes = saved.homes || 1;
    costLtv = saved.ltv != null ? saved.ltv : 40;
    Object.assign(costPrice, saved.price || {});
    Object.assign(costBucket, saved.bucket || {});
  } catch { /* 기본값 */ }

  function saveCost() {
    localStorage.setItem("seoul_apt_cost", JSON.stringify(
      { ids: costIds, homes: costHomes, ltv: costLtv, price: costPrice, bucket: costBucket }));
  }
  function addCost(id) {
    if (costIds.includes(id)) return;
    if (costIds.length >= COST_MAX) costIds.shift();
    costIds.push(id);
    saveCost(); renderCostBody();
  }
  // 단지가 매매가를 가진 평형대 버킷 목록(표준 순서)
  function costBuckets(mk) {
    const sa = mk.sale_area || {};
    return COST_BUCKET_ORDER.filter((b) => sa[b] && sa[b].p);
  }
  // 현재 선택된(또는 대표) 평형대
  function costSelBucket(mk) {
    const avail = costBuckets(mk);
    const sel = costBucket[mk.id];
    if (sel && avail.includes(sel)) return sel;
    if (mk.rep && avail.includes(mk.rep)) return mk.rep;
    return avail[0] || null;
  }
  // 선택 평형대의 기본 매수가(만원)·전용면적(㎡)·평
  function costDefaults(mk) {
    const b = costSelBucket(mk);
    const o = b && mk.sale_area ? mk.sale_area[b] : null;
    const price = o ? o.p : (mk.sale || null);
    // 농특세 판정은 버킷으로(app.js calcCost) — py 는 정수 반올림이라 ㎡ 역환산 금지
    return { price, py: o ? o.py : null, bucket: b };
  }

  async function renderCost() {
    if (!$("cost-table-wrap")) return;
    (meta.districts || []).forEach((d) => { GU_NAME[d.lawd_cd] = d.name; });
    await loadMk();
    bindCostBar();
    $("cost-homes").value = String(costHomes);
    $("cost-ltv").value = String(costLtv);
    $("cost-ltv-val").textContent = costLtv + "%";
    renderCostBody();
    renderCostNotice();
  }

  function renderCostNotice() {
    $("cost-notice").innerHTML =
      `<b>2026-07 규제 반영</b> · 서울 전역 규제지역 — 무주택·1주택 주담대 <b>LTV 40%</b>,
       한도 <b>15억↓ 6억 / 15~25억 4억 / 25억↑ 2억</b>.
       <b>2주택 이상은 구입 목적 주담대 금지</b>(대출 0 · 전액 현금).
       취득세 서울 전역 조정지역(2주택 8%·3주택+ 12%).
       토지거래허가구역은 <b>2년 실거주 의무</b>(갭투자 제한),
       1주택 전세대출도 DSR 반영(스트레스금리 3%).<br>
       <span class="muted">참고용 · 국민주택채권·보유세·DSR 개인한도·생애최초 우대 등은
       미반영. 실제 세액·대출은 개인 조건·정책 변경에 따라 다를 수 있습니다.</span>`;
  }

  function costWon(v) {
    return v >= 10000 ? SeoulCharts.fmt(Math.round(v))
      : Math.round(v).toLocaleString() + "만";
  }

  function renderCostBody() {
    const wrap = $("cost-table-wrap");
    const mks = costIds.map((id) => mkAll.find((m) => m.id === id)).filter(Boolean);
    if (!mks.length) {
      wrap.innerHTML = '<div class="empty">지도 가격 푯말을 드래그하거나 단지명을 검색해 추가하세요.</div>';
      return;
    }
    const calc = window.SeoulMap && SeoulMap.calcCost;
    const rows = [
      ["평형대", (m, c, def) => {
        const avail = costBuckets(m);
        if (avail.length <= 1) {
          return def.bucket ? `${def.bucket}${def.py ? ` <span class="muted">${def.py}평</span>` : ""}` : "-";
        }
        return `<select class="cost-bucket-sel" data-id="${m.id}">`
          + avail.map((b) => {
            const o = m.sale_area[b];
            return `<option value="${b}"${b === def.bucket ? " selected" : ""}>${b}${o.py ? ` (${o.py}평)` : ""}</option>`;
          }).join("") + "</select>";
      }],
      ["매수가(만원)", (m, c, def) =>
        `<input class="cost-price-inp" data-id="${m.id}" type="number" step="1000" min="0"
           value="${costPrice[m.id] != null ? costPrice[m.id] : (def.price || 0)}">`],
      ["취득세", (m, c) => c ? `${costWon(c.acq)} <span class="muted">(${c.acqRate.toFixed(1)}%)</span>` : "-"],
      ["지방교육세", (m, c) => c ? costWon(c.edu) : "-"],
      ["농특세", (m, c) => c && c.farm ? costWon(c.farm) : "-"],
      ["중개보수", (m, c) => c ? `${costWon(c.brok)} <span class="muted">(${c.brokRate}%+VAT)</span>` : "-"],
      ["기타(인지·법무)", (m, c) => c ? costWon(c.etc) : "-"],
      ["부대비용 합계", (m, c) => c ? `<b>${costWon(c.costs)}</b>` : "-"],
      ["대출금", (m, c) => !c ? "-"
        : c.loanBanned
          ? `−0 <span class="cost-cap">다주택 구입 주담대 금지</span>`
          : `−${costWon(c.loan)}${c.loanCapped ? ` <span class="cost-cap">한도 ${costWon(c.loanCap)}</span>` : ""}`],
      ["필요 현금", (m, c) => c ? `<b class="cost-cash">${costWon(c.cash)}</b>` : "-"],
    ];
    let html = `<table class="rank-table cmp-table cost-table2"><thead><tr><th></th>`
      + mks.map((m, i) => `<th class="cmp-head" data-id="${m.id}">
          <i style="background:${COLORS[i % COLORS.length]}"></i>${esc(m.apt)}
          <b class="cost-del" data-del="${m.id}" title="제거">✕</b></th>`).join("")
      + "</tr></thead><tbody>";
    rows.forEach(([label, fn]) => {
      html += `<tr><td class="cmp-label">${label}</td>`
        + mks.map((m) => {
          const def = costDefaults(m);
          const price = costPrice[m.id] != null ? costPrice[m.id] : (def.price || 0);
          const c = calc && price ? calc(price, costHomes, costLtv, def.bucket) : null;
          return `<td>${fn(m, c, def)}</td>`;
        }).join("") + "</tr>";
    });
    wrap.innerHTML = html + "</tbody></table>";
    // 열 헤더 클릭 = 지도, ✕ = 제거
    wrap.querySelectorAll(".cmp-head").forEach((th) =>
      th.addEventListener("click", (e) => {
        if (e.target.classList.contains("cost-del")) return;
        if (window.SeoulMap) window.SeoulMap.focusComplex(+th.dataset.id);
      }));
    wrap.querySelectorAll(".cost-del").forEach((b) =>
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        costIds = costIds.filter((x) => x !== +b.dataset.del);
        delete costPrice[+b.dataset.del];
        delete costBucket[+b.dataset.del];
        saveCost(); renderCostBody();
      }));
    // 평형대 변경 → 그 평형 매매가로 초기화(수기 편집값 제거) 후 재계산
    wrap.querySelectorAll(".cost-bucket-sel").forEach((sel) =>
      sel.addEventListener("change", () => {
        const id = +sel.dataset.id;
        costBucket[id] = sel.value;
        delete costPrice[id];   // 선택 평형 기본가로 되돌림
        saveCost(); renderCostBody();
      }));
    // 매수가 편집 → 즉시 재계산
    wrap.querySelectorAll(".cost-price-inp").forEach((inp) =>
      inp.addEventListener("input", () => {
        costPrice[+inp.dataset.id] = +inp.value || 0;
        saveCost(); renderCostBody();
      }));
  }

  function bindCostBar() {
    const inp = $("cost-search");
    if (inp._bound) return;
    inp._bound = true;
    inp.addEventListener("input", () => {
      const q = inp.value.trim();
      if (q.length < 2 || q.includes("#")) return;
      const hits = mkAll.filter((m) => m.apt.includes(q)).slice(0, 20);
      $("cost-datalist").innerHTML = hits.map((m) =>
        `<option value="${esc(m.apt)} · ${GU_NAME[m.lawd_cd] || m.lawd_cd} #${m.id}">`).join("");
    });
    inp.addEventListener("change", () => {
      const mch = inp.value.match(/#(\d+)$/);
      if (!mch) return;
      addCost(+mch[1]);
      inp.value = "";
    });
    $("cost-homes").addEventListener("change", (e) => {
      costHomes = +e.target.value; saveCost(); renderCostBody();
    });
    $("cost-ltv").addEventListener("input", (e) => {
      costLtv = +e.target.value;
      $("cost-ltv-val").textContent = costLtv + "%";
      saveCost(); renderCostBody();
    });
    $("cost-load-fav").addEventListener("click", () => {
      let favs = [];
      try { favs = JSON.parse(localStorage.getItem("seoul_apt_favs") || "[]"); }
      catch { favs = []; }
      favs.forEach((f) => { if (costIds.length < COST_MAX && !costIds.includes(f.id)) costIds.push(f.id); });
      saveCost(); renderCostBody();
    });
    $("cost-clear").addEventListener("click", () => {
      costIds = []; saveCost(); renderCostBody();
    });
    // 지도 가격 푯말 드래그 → 이 패널에 드롭하면 추가
    const dz = $("cost-panel");
    if (dz && !dz._dropBound) {
      dz._dropBound = true;
      dz.addEventListener("dragover", (e) => {
        if ((e.dataTransfer.types || []).indexOf("text/plain") >= 0) {
          e.preventDefault(); e.dataTransfer.dropEffect = "copy";
          dz.classList.add("cmp-drop");
        }
      });
      dz.addEventListener("dragleave", (e) => {
        if (!dz.contains(e.relatedTarget)) dz.classList.remove("cmp-drop");
      });
      dz.addEventListener("drop", (e) => {
        const d = e.dataTransfer.getData("text/plain");
        dz.classList.remove("cmp-drop");
        if (d && d.indexOf("cmp:") === 0) { e.preventDefault(); addCost(+d.slice(4)); }
      });
    }
  }

  // ── 6) 청약·분양 (서울) ─────────────────────────────────────────────
  // 공급유형 태그(무순위/불법행위 재공급/임의공급/일반공급)
  function subTypeTag(it) {
    const secd = it.secd && it.secd !== "일반공급" ? it.secd
      : it.kind === "remndr" ? "무순위/잔여"
      : it.kind === "optn" ? "임의공급" : "일반공급";
    const cls = secd.indexOf("불법") >= 0 ? "st-illegal"
      : secd.indexOf("임의") >= 0 ? "st-optn"
      : secd.indexOf("무순위") >= 0 || secd.indexOf("잔여") >= 0 ? "st-remndr"
      : "st-normal";
    return `<span class="sub-type ${cls}">${secd}</span>`;
  }

  function subStatus(it) {
    const d = new Date();
    const t = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (it.rcept_bgn && t < it.rcept_bgn) return { k: "upcoming", label: "예정" };
    if (it.rcept_end && t <= it.rcept_end) return { k: "open", label: "접수중" };
    if (it.przwner && t < it.przwner) return { k: "wait", label: "발표대기" };
    return { k: "done", label: "완료" };
  }

  // 접수기간을 좁은 패널에서 한 줄에 들어가게 축약.
  // 같은 날이면 하루짜리(무순위·임의공급 다수)라 한 번만, 같은 해면 종료일의
  // 연도를 생략한다("2026-07-27 ~ 2026-07-30" → "2026-07-27 ~ 07-30").
  function subPeriod(it) {
    const b = it.rcept_bgn, e = it.rcept_end;
    if (!b && !e) return "기간 미정";
    if (!e || b === e) return b || e;
    if (!b) return `~ ${e}`;
    return `${b} ~ ${e.slice(0, 4) === b.slice(0, 4) ? e.slice(5) : e}`;
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
    // 지금 넣을 수 있는 건(접수중)과 곧 열리는 건(예정)을 건수로 먼저 알려준다.
    // 접수중이 0이어도 예정이 있으면 '없다'고 오해하지 않도록.
    const cnt = { open: 0, upcoming: 0, wait: 0 };
    active.forEach((it) => { cnt[subStatus(it).k] += 1; });
    const summary = `<div class="subs-summary">
      <span class="badge sub-badge-open">접수중 ${cnt.open}건</span>
      <span class="badge sub-badge-upcoming">접수 예정 ${cnt.upcoming}건</span>
      <span class="badge sub-badge-wait">발표대기 ${cnt.wait}건</span></div>`;
    if (!active.length) {
      wrap.innerHTML = summary + '<div class="empty">진행중·예정 청약 없음</div>';
    } else {
      // 표(9열)가 아니라 카드로 쌓는다. 이 패널은 폭이 460px 안팎이라 9열을
      // 넣으면 주택명 칸이 30px대로 눌려 한 글자씩 세로로 쪼개졌다(행높이 245px+).
      let html = summary + '<div class="sub-list">';
      active.forEach((it) => {
        const st = subStatus(it);
        const top = Math.max(0, ...(it.models || []).map((m) => m.price || 0));
        const mgns = (it.models || []).filter((m) => m.mgn != null).map((m) => m.mgn);
        const bm = mgns.length ? Math.max(...mgns) : null;
        const link = it.url
          ? `<a class="sub-link" href="${it.url}" target="_blank" rel="noopener" title="청약홈 공고 보기">↗</a>` : "";
        // 웹 캘린더 보조 공고는 일정만 있고 세대·분양가·안전마진이 비어 있다.
        // '-' 만 뜨면 데이터 누락처럼 보이므로 출처를 표시해 준다.
        const prov = it.src === "web"
          ? ' <span class="sub-prov" title="청약홈 캘린더에서 먼저 확인된 공고입니다. 공공데이터 반영 후 세대수·분양가·안전마진이 채워집니다.">캘린더</span>'
          : "";
        // 각 항목을 span 으로 감싸야 .sc-meta 의 flex gap 이 먹는다
        // (맨텍스트로 이어 붙이면 '15억안전마진' 처럼 딱 붙어 보임)
        const facts = [
          top ? `<span>분양가 <b>${SeoulCharts.fmt(top)}</b></span>` : "",
          bm == null ? ""
            : `<span>안전마진 <span class="mgn ${bm > 0 ? "pos" : "neg"}">${bm > 0 ? "+" : ""}${bm}%</span></span>`,
        ].filter(Boolean).join("");
        html += `<div class="sub-card" data-lat="${it.lat || ""}" data-lon="${it.lon || ""}">
          <div class="sc-top">
            <span class="badge sub-badge-${st.k}">${st.label}</span>
            <span class="sc-name">${esc(it.name)}${prov}</span>${link}
          </div>
          <div class="sc-meta">
            ${subTypeTag(it)}
            ${it.gu ? `<span>${it.gu}</span>` : ""}
            ${it.tot ? `<span>${it.tot.toLocaleString()}세대</span>` : ""}
            <span class="sc-date">${subPeriod(it)}</span>
          </div>
          ${facts ? `<div class="sc-meta">${facts}</div>` : ""}
        </div>`;
      });
      wrap.innerHTML = html + "</div>";
      bindSubRows(wrap);
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
      <th>주택명</th><th>구</th><th>접수마감</th><th>최고 경쟁률</th><th>청약홈</th>
      </tr></thead><tbody>`;
    rated.forEach(({ it, best }) => {
      const link = it.url
        ? `<a class="sub-link" href="${it.url}" target="_blank" rel="noopener" title="청약홈 공고 보기">↗</a>` : "-";
      ch += `<tr data-lat="${it.lat || ""}" data-lon="${it.lon || ""}">
        <td>${esc(it.name)}</td><td>${it.gu || "-"}</td>
        <td>${it.rcept_end || "-"}</td><td>${best.toLocaleString()} : 1</td>
        <td>${link}</td></tr>`;
    });
    cwrap.innerHTML = ch + "</tbody></table>";
    bindSubRows(cwrap);
  }

  // 청약 표 공통: 행 클릭=지도 이동(청약홈 링크 클릭은 제외)
  // 진행중·예정은 카드(.sub-card), 경쟁률은 표(tr) — 둘 다 좌표가 있으면 클릭 시 지도 이동
  function bindSubRows(wrap) {
    wrap.querySelectorAll("[data-lat]").forEach((el) => {
      if (!el.dataset.lat) return;
      el.classList.add("row-clickable");
      el.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;   // 청약홈 링크는 통과
        if (window.SeoulMap) window.SeoulMap.focusLatLng(+el.dataset.lat, +el.dataset.lon);
      });
    });
  }

  // ── 7) 종합점수 — 입지·단지·가격·유동성 절대 기준 채점 랭킹 ─────────────
  // 설계 원칙(2026-07-30 사용자 확정):
  //  · 지표별 절대 구간표 + 선형 보간(경계 점프 방지) → 0~100 지표점수
  //  · 축 내 가중평균 → 프리셋 축 가중합 = 총점. 등급 S85/A75/B60/C45/D
  //  · 결측은 감점이 아니라 제외 후 재가중(데이터 유무가 점수를 왜곡하면 안 됨)
  //    단, 지하철/초등 null 은 '상한(2km/1.5km) 밖 확정'이라 결측이 아닌 최저점
  //  · 가격 축은 선택 평형 기준(전 평형 혼합 금지 - 프로젝트 대원칙)
  //  · 구 시장국면은 점수에 넣지 않고 배지로만(단지 자체 평가와 분리)
  const SC_PRESETS = {
    live:   { label: "🏠 실거주형", axes: { loc: 35, cx: 25, price: 25, liq: 15 },
              price: { pos: 40, jr: 30, drop: 15, prem: 15 } },
    invest: { label: "📈 투자형",   axes: { loc: 25, cx: 15, price: 35, liq: 25 },
              price: { pos: 40, jr: 30, drop: 15, prem: 15 } },
    // 갭투자는 '현금이 얼마나 묶이나'가 핵심 → 절대 갭 금액이 주 지표
    gap:    { label: "🔁 갭투자형", axes: { loc: 20, cx: 15, price: 40, liq: 25 },
              price: { gap: 45, jr: 20, pos: 20, prem: 15 } },
  };
  // 지표별 구간표 [x, 점수] — x 오름차순, 사이는 선형 보간, 양끝은 고정
  const SC_PTS = {
    sw:   [[300, 100], [500, 85], [800, 65], [1200, 40], [2000, 15]],
    el:   [[300, 100], [600, 80], [1000, 55], [1500, 25]],
    // 직주근접: 3대 업무지구(강남·시청/광화문·여의도) 최단 직선거리(km).
    // '강남 역세권 vs 강북 역세권' 차이를 잡는 핵심 지표.
    cbd:  [[2, 100], [4, 85], [7, 65], [11, 45], [15, 28], [20, 15]],
    // 학원 밀집도(반경 1km, 카카오 AC5 전 종류): 실측 보정 -
    // 대치 1,689 / 목동 596 / 중계 338 / 일반 활발지 150~250
    ac:   [[5, 15], [20, 40], [60, 60], [150, 75], [300, 85], [600, 95], [1200, 100]],
    hh:   [[0, 25], [300, 45], [500, 60], [1000, 75], [1500, 88], [3000, 100]],
    age:  [[5, 100], [10, 85], [15, 70], [25, 50], [35, 35], [50, 25]],
    pos:  [[20, 100], [35, 85], [50, 65], [65, 45], [80, 30], [100, 15]],
    jr:   [[30, 25], [40, 45], [50, 65], [60, 85], [70, 100]],
    drop: [[-15, 100], [-10, 85], [-5, 60], [0, 25]],   // drop은 음수(하락)
    prem: [[-5, 100], [-2, 80], [2, 55], [5, 35], [10, 15]],
    gap:  [[1, 100], [2, 85], [3, 70], [5, 50], [8, 30], [12, 15]],  // 억
    turn: [[0, 15], [0.7, 30], [1.5, 45], [2.5, 65], [4, 85], [6, 100]],  // %
    lst:  [[1, 70], [5, 100]],                          // open 매물 건수
  };
  const SC_GRADES = [[85, "S"], [75, "A"], [60, "B"], [45, "C"], [-1, "D"]];
  const SC_AXIS_KO = { loc: "입지", cx: "단지", price: "가격", liq: "유동성" };
  const PHASE_ICON = { boom: "🔥", recovery: "🌱", slowdown: "🌥️",
                       recession: "❄️", neutral: "⚪" };

  // 3대 업무지구(직주근접 기준점): 강남역 · 시청(광화문 생활권) · 여의도역
  const SC_CBD = [[37.4979, 127.0276], [37.5657, 126.9769], [37.5216, 126.9243]];
  function scCbdKm(lat, lon) {
    const R = 6371, rad = Math.PI / 180;
    let best = null;
    SC_CBD.forEach(([la, lo]) => {
      const dLa = (la - lat) * rad, dLo = (lo - lon) * rad;
      const a = Math.sin(dLa / 2) ** 2
        + Math.cos(lat * rad) * Math.cos(la * rad) * Math.sin(dLo / 2) ** 2;
      const d = 2 * R * Math.asin(Math.sqrt(a));
      if (best == null || d < best) best = d;
    });
    return best;
  }

  function scInterp(v, pts) {
    if (v == null || !isFinite(v)) return null;
    if (v <= pts[0][0]) return pts[0][1];
    if (v >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
    for (let i = 1; i < pts.length; i++) {
      if (v <= pts[i][0]) {
        const [x0, s0] = pts[i - 1], [x1, s1] = pts[i];
        return s0 + (s1 - s0) * (v - x0) / (x1 - x0);
      }
    }
    return pts[pts.length - 1][1];
  }
  // 축 점수 = 있는 지표만으로 가중평균(결측 제외·재가중). 전부 없으면 null.
  function scAxis(parts) {
    let ws = 0, acc = 0;
    parts.forEach(([s, w]) => { if (s != null) { acc += s * w; ws += w; } });
    return ws ? acc / ws : null;
  }
  const scMedian = (a) => {
    if (!a.length) return null;
    const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };

  // ── 가격 매력의 '동급 대비' 보정 ──
  // 가격 지표는 품질과 역상관이다: 입지가 나쁘면 랠리에서 소외돼 5년위치가 낮고,
  // 전세가율은 강북이 구조적으로 높고, 갭은 싼 단지가 당연히 작다. 절대 구간표로
  // 두면 '나빠서 싼' 단지가 가격 만점으로 종합점수를 끌어올린다(가치 함정 오인 -
  // 사용자 지적). → 품질 종합 Q(입지60·단지40)로 전체를 5분위로 나누고,
  // pos/jr/drop 은 **같은 분위 안 백분위**로 점수화("이 급치고 싼가?").
  // 호가괴리(자기 실거래 대비 - 이미 오염 없음)와 갭 금액(갭투자는 실제 묶이는
  // 현금이 본질)은 절대값 유지.
  function scBuildPeers(recs) {
    const withQ = recs.filter((r) => r.q != null);
    if (withQ.length < 50) return null;              // 표본 부족 시 절대 구간표 폴백
    const qs = withQ.map((r) => r.q).sort((a, b) => a - b);
    const bounds = [1, 2, 3, 4].map((i) => qs[Math.floor(qs.length * i / 5)]);
    const grpOf = (q) => bounds.findIndex((b) => q < b) === -1
      ? 4 : bounds.findIndex((b) => q < b);
    const groups = [[], [], [], [], []].map(() => ({ pos: [], jr: [], drop: [] }));
    withQ.forEach((r) => {
      const g = groups[grpOf(r.q)];
      ["pos", "jr", "drop"].forEach((k) => {
        if (r.raw[k] != null) g[k].push(r.raw[k]);
      });
    });
    groups.forEach((g) => Object.values(g).forEach((a) => a.sort((x, y) => x - y)));
    // 백분위(0~100, midrank): 동급 분포에서 v 이하 비율
    const pct = (gi, key, v) => {
      const a = groups[gi][key];
      if (!a || a.length < 20 || v == null) return null;
      let lo = 0, hi = a.length;
      while (lo < hi) { const m = (lo + hi) >> 1; (a[m] < v) ? lo = m + 1 : hi = m; }
      let lo2 = lo, hi2 = a.length;
      while (lo2 < hi2) { const m = (lo2 + hi2) >> 1; (a[m] <= v) ? lo2 = m + 1 : hi2 = m; }
      return (lo + lo2) / 2 / a.length * 100;
    };
    return { grpOf, pct };
  }

  function scoreComplex(m, val, prem, preset, bucket, peers) {
    const P = SC_PRESETS[preset];
    const nowYear = new Date().getFullYear();
    // 입지: 거리(sw/el null = 상한 밖 확정 → 최저점) + 퀄리티 보정 3종.
    //  · 지하철 = 거리점수 × 노선계수(환승 프리미엄: 2노선 ×1.05, 3+ ×1.10)
    //  · 직주근접 = 3대 업무지구 최단거리 - '강남 역세권 vs 강북 역세권' 차별화
    //  · 학원가 = 반경 1km 학원 수(학군 프록시, 수집 전 단지는 제외·재가중)
    const lineMul = 1 + 0.05 * (Math.min(m.swl || 1, 3) - 1);
    let swScore = scInterp(m.sw == null ? 9999 : m.sw, SC_PTS.sw) * lineMul;
    // 경전철(우이신설·신림 등)은 수송력·속도·간선 연결성이 지하철보다 낮다
    // → 역세권 프리미엄 25% 할인(벽산라이브파크가 우이신설 257m 로 지하철급
    //   92점을 받아 전체 상위권에 오르던 왜곡 - 사용자 정성 지적으로 교정)
    if (m.swn && /우이신설|신림선|경량/.test(m.swn)) swScore *= 0.75;
    swScore = Math.min(100, swScore);
    const loc = scAxis([
      [swScore, 35],
      [scInterp(scCbdKm(m.lat, m.lon), SC_PTS.cbd), 25],
      [m.ac != null ? scInterp(m.ac, SC_PTS.ac) : null, 25],
      [scInterp(m.el == null ? 9999 : m.el, SC_PTS.el), 15],
    ]);
    // 단지: 건축물대장 미수집(hh/by null)은 제외·재가중
    let cx = scAxis([
      [m.hh != null ? scInterp(m.hh, SC_PTS.hh) : null, 55],
      [m.by ? scInterp(nowYear - m.by, SC_PTS.age) : null, 45],
    ]);
    // ♻ 재건축 잠재 보너스: 연차 30+ & 용적률<160% (그냥 늙은 단지는 만회 불가)
    const redev = !!(m.by && (nowYear - m.by) >= 30 && m.far != null && m.far < 160);
    if (redev && cx != null) cx = Math.min(100, cx + 20);
    // 가격: 선택 평형 기준. v=밸류에이션(버킷 스코프), gap=같은 평형 매매-전세
    const b = bucket || m.rep;
    const v = val ? (bucket ? (val.areas || {})[bucket] : val.all) : null;
    const jrVal = bucket ? (v ? v.jr : null) : (m.jeonse_ratio != null ? m.jeonse_ratio : (v ? v.jr : null));
    const s = b && m.sale_area ? m.sale_area[b] : null;
    const j = b && m.jeonse_area ? m.jeonse_area[b] : null;
    const gapEok = (s && j) ? (s.p - j.p) / 10000 : null;
    // 품질 종합 Q(입지60·단지40) — 가격 상대화의 분위 기준(1패스에서 수집)
    const q = scAxis([[loc, 60], [cx, 40]]);
    const posRaw = (v && v.pos != null) ? v.pos : null;
    const dropRaw = m.drop != null ? m.drop : null;
    // 동급(품질 분위) 내 백분위 점수. invert=낮을수록 좋은 지표.
    // 피어 통계가 없으면 null → 절대 구간표 폴백
    const rel = (key, vRaw, invert) => {
      if (!peers || q == null || vRaw == null) return null;
      const p = peers.pct(peers.grpOf(q), key, vRaw);
      return p == null ? null : (invert ? 100 - p : p);
    };
    const priceParts = [];
    if (P.price.pos) {
      const rs = rel("pos", posRaw, true);
      priceParts.push([rs != null ? rs
        : (posRaw != null ? scInterp(posRaw, SC_PTS.pos) : null), P.price.pos]);
    }
    if (P.price.jr) {
      const rs = rel("jr", jrVal, false);
      priceParts.push([rs != null ? rs : scInterp(jrVal, SC_PTS.jr), P.price.jr]);
    }
    if (P.price.drop) {
      const rs = rel("drop", dropRaw, true);
      priceParts.push([rs != null ? rs
        : (dropRaw != null ? scInterp(dropRaw, SC_PTS.drop) : null), P.price.drop]);
    }
    if (P.price.gap)  priceParts.push([scInterp(gapEok, SC_PTS.gap), P.price.gap]);
    if (P.price.prem) priceParts.push([prem != null ? scInterp(prem, SC_PTS.prem) : null, P.price.prem]);
    let price = scAxis(priceParts);
    // 신뢰도 수축: 재가중만 하면 지표 1개(예: 고점대비)만으로 가격 98점이 된다
    // (실측 - 에비뉴나인티가 drop 단독으로 1위). 결측 비중만큼 중립(50)으로 수축.
    if (price != null) {
      const totW = priceParts.reduce((a, [, wt]) => a + wt, 0);
      const usedW = priceParts.reduce((a, [s, wt]) => a + (s != null ? wt : 0), 0);
      price = 50 + (price - 50) * Math.sqrt(usedW / totW);
    }
    // 유동성: 회전율(세대수 필요) + 매물 활발도(미수집 단지는 제외 - 수집 여부로 벌점 금지)
    const nls = (m.ls || 0) + (m.lj || 0);
    const liq = scAxis([
      [(m.hh && m.n1y != null) ? scInterp(m.n1y / m.hh * 100, SC_PTS.turn) : null, 70],
      [nls > 0 ? scInterp(nls, SC_PTS.lst) : null, 30],
    ]);
    const axes = { loc, cx, price, liq };
    let ws = 0, acc = 0, used = 0;
    Object.keys(P.axes).forEach((k) => {
      if (axes[k] != null) { acc += axes[k] * P.axes[k]; ws += P.axes[k]; used++; }
    });
    if (!ws) return null;
    let total = acc / ws;
    // 품질 연동 상한: 가격·유동성만으로는 품질(Q) 대비 +15점을 넘을 수 없다.
    // "나머지 점수는 낮은데 가격 점수가 높아 종합점수가 너무 높은" 왜곡 차단
    // (사용자 정성 지적). S등급(85+)이 되려면 최소 Q 70(상위 2분위)이 필요해진다.
    const qcap = q != null && total > q + 15;
    if (qcap) total = q + 15;
    return {
      total, axes, redev, qcap, usedAxes: used,
      grade: SC_GRADES.find(([t]) => total >= t)[1],
      lowSample: m.n1y != null && m.n1y < 3,
      q, raw: { pos: posRaw, jr: jrVal, drop: dropRaw },
    };
  }

  // ── 종합점수 패널 렌더 ──
  let scLst = null, scValById = null, scPhaseByGu = null;
  let scLimit = 100;                 // 표시 개수(더보기로 +200씩, 조건 변경 시 리셋)
  const SC_LS_KEY = "seoul_apt_score_v1";
  let scState = (() => {
    try { return JSON.parse(localStorage.getItem(SC_LS_KEY)) || {}; }
    catch { return {}; }
  })();
  scState = Object.assign({ preset: "live", bucket: "", gu: "" }, scState);
  const scSave = () => localStorage.setItem(SC_LS_KEY, JSON.stringify(scState));

  async function renderScore() {
    const list = $("sc-list");
    if (!list) return;                       // 독립 dashboard.html 에는 없음
    await loadMk();
    if (!valData) {
      try { valData = await fetchJSON(DATA + "valuation.json"); } catch { valData = { items: [] }; }
    }
    if (!scLst) {
      try { scLst = (await fetchJSON(DATA + "listings.json")).complexes || {}; }
      catch { scLst = {}; }
    }
    if (!scValById) {
      scValById = {};
      (valData.items || []).forEach((it) => { scValById[it.id] = it; });
    }
    if (!scPhaseByGu && dash && dash.market_phase) {
      scPhaseByGu = {};
      dash.market_phase.forEach((r) => { scPhaseByGu[r.lawd_cd] = r.phase; });
    }
    (meta.districts || []).forEach((d) => { GU_NAME[d.lawd_cd] = d.name; });

    // 컨트롤(프리셋·평형·구) — 매 렌더 재생성(상태 반영)
    $("sc-presets").innerHTML = Object.entries(SC_PRESETS).map(([k, p]) =>
      `<button class="d-chip sc-chip${scState.preset === k ? " on" : ""}" data-preset="${k}">${p.label}</button>`).join("");
    const buckets = ["", "~60㎡", "60~85㎡", "85~135㎡", "135㎡~"];
    $("sc-buckets").innerHTML = buckets.map((b) =>
      `<button class="d-chip sc-chip${scState.bucket === b ? " on" : ""}" data-bucket="${b}">${b || "전체(대표평형)"}</button>`).join("");
    const guSel = $("sc-gu");
    if (guSel.options.length <= 1) {
      (meta.districts || []).forEach((d) => {
        const o = document.createElement("option");
        o.value = d.lawd_cd; o.textContent = d.name;
        guSel.appendChild(o);
      });
    }
    guSel.value = scState.gu;
    $("sc-presets").querySelectorAll("[data-preset]").forEach((btn) =>
      btn.addEventListener("click", () => { scState.preset = btn.dataset.preset; scLimit = 100; scSave(); renderScore(); }));
    $("sc-buckets").querySelectorAll("[data-bucket]").forEach((btn) =>
      btn.addEventListener("click", () => { scState.bucket = btn.dataset.bucket; scLimit = 100; scSave(); renderScore(); }));
    if (!guSel._scBound) {
      guSel._scBound = true;
      guSel.addEventListener("change", () => { scState.gu = guSel.value; scLimit = 100; scSave(); renderScore(); });
    }

    // 단지별 매물 호가 괴리(중앙값) — 선택 평형이 있으면 그 평형 매물만
    const premOf = (id) => {
      const g = scLst[String(id)];
      if (!g) return null;
      const rows = (g.sale || []).filter((r) => r.prem != null
        && (!scState.bucket || r.b === scState.bucket));
      return rows.length ? scMedian(rows.map((r) => r.prem)) : null;
    };

    // 채점: 특정 평형 선택 시 그 평형 매매 데이터가 있는 단지만(매수후보와 동일 규칙)
    // 1패스: 전체 서울(버킷 적격)에서 품질 Q·가격 원시값 수집 → 품질 5분위 피어 분포.
    // 구 필터는 표시만 거르고 피어 통계는 전체 서울로 고정(구를 좁혀도 채점 기준 불변).
    const pool = mkAll.filter((m) =>
      !scState.bucket || (m.sale_area && m.sale_area[scState.bucket]));
    const pre = pool.map((m) =>
      scoreComplex(m, scValById[m.id], premOf(m.id), scState.preset, scState.bucket, null));
    const peers = scBuildPeers(pre.filter(Boolean).map((r) => ({ q: r.q, raw: r.raw })));
    // 2패스: 동급 상대화 점수로 확정
    // 최소 3축 요건: 결측은 감점하지 않되, 축이 2개 이하면 '판단 불가'로 순위 제외.
    // (안 그러면 가격·유동성 데이터가 없는 나홀로 신축이 입지+단지 2축 만점으로
    //  상위권을 오염 - 실측에서 1~3위가 전부 2/4축 단지였음)
    const scored = [];
    let thin = 0;
    pool.forEach((m) => {
      if (scState.gu && m.lawd_cd !== scState.gu) return;
      const r = scoreComplex(m, scValById[m.id], premOf(m.id), scState.preset, scState.bucket, peers);
      if (!r) return;
      if (r.usedAxes < 3) { thin++; return; }
      scored.push({ m, r });
    });
    scored.sort((a, b) => b.r.total - a.r.total);

    const shown = Math.min(scLimit, scored.length);
    $("sc-note").textContent =
      `${SC_PRESETS[scState.preset].label} 기준 ${scored.length.toLocaleString()}개 단지 채점 · 1~${shown.toLocaleString()}위 표시`
      + (scState.bucket ? ` · ${scState.bucket} 매매 데이터 보유 단지만` : "")
      + (thin ? ` · 데이터 2축 이하 ${thin.toLocaleString()}개 제외` : "")
      + (peers ? " · 가격축=품질 동급(5분위) 상대평가" : "");

    const bar = (v) => v == null
      ? '<i class="sc-b none"></i>'
      : `<i class="sc-b"><b style="width:${Math.round(v)}%"></b></i>${Math.round(v)}`;
    list.innerHTML = scored.slice(0, scLimit).map(({ m, r }, i) => {
      const ph = scPhaseByGu && scPhaseByGu[m.lawd_cd];
      const badges = [
        r.redev ? '<span class="sc-tag redev" title="연차 30년+ · 용적률 160% 미만 → 단지 축 +20">♻재건축</span>' : "",
        r.qcap ? '<span class="sc-tag warn" title="가격·유동성 점수가 품질(입지·단지) 대비 과도해 총점을 품질+15로 제한">💰상한</span>' : "",
        r.lowSample ? '<span class="sc-tag warn" title="최근 1년 매매 3건 미만 - 통계 신뢰도 낮음">⚠표본</span>' : "",
        r.usedAxes < 4 ? `<span class="sc-tag warn" title="데이터 없는 축은 제외하고 재가중">${r.usedAxes}/4축</span>` : "",
      ].join("");
      return `<div class="sc-card" data-id="${m.id}">
        <div class="sc-top">
          <span class="sc-rank">${i + 1}</span>
          <span class="sc-name">${esc(m.apt)}</span>${badges}
          <span class="sc-grade g-${r.grade}">${r.grade} ${Math.round(r.total)}</span>
        </div>
        <div class="sc-axes">${Object.keys(SC_AXIS_KO).map((k) =>
          `<span class="sc-ax">${SC_AXIS_KO[k]} ${bar(r.axes[k])}</span>`).join("")}</div>
        <div class="sc-meta">${GU_NAME[m.lawd_cd] || ""}${ph ? ` ${PHASE_ICON[ph]}${PHASE_LABEL[ph]}` : ""}
          ${m.hh ? ` · ${m.hh.toLocaleString()}세대` : ""}${m.by ? ` · ${new Date().getFullYear() - m.by}년차` : ""}
          ${m.sw != null ? ` · 역 ${m.sw}m${m.swl > 1 ? `(${m.swl}노선)` : ""}` : ""}
          ${m.ac != null ? ` · 학원 ${m.ac}` : ""}</div>
      </div>`;
    }).join("") || '<div class="empty">조건에 맞는 단지 없음</div>';

    // 101위 이후도 보기: 한 번에 다 그리면 DOM이 무거워(전체 ~9천 카드) 200개씩 추가
    if (scored.length > scLimit) {
      const more = document.createElement("button");
      more.className = "sc-more";
      more.textContent = `더보기 (${(shown + 1).toLocaleString()}~${Math.min(scLimit + 200, scored.length).toLocaleString()}위 · 전체 ${scored.length.toLocaleString()}개)`;
      more.addEventListener("click", () => { scLimit += 200; renderScore(); });
      list.appendChild(more);
    }

    list.querySelectorAll(".sc-card").forEach((c) =>
      c.addEventListener("click", () => {
        if (window.SeoulMap) SeoulMap.focusComplex(+c.dataset.id, scState.bucket || undefined);
      }));
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });  // 매일 갱신 데이터 → 항상 최신
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
})();
