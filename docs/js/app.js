/* 서울 아파트 시세 지도 - 메인 앱 */
(function () {
  "use strict";

  const DATA = "data/";
  const SEOUL_CENTER = { lat: 37.5665, lng: 126.978 };
  const BUBBLE_CAP = 250;            // 화면에 동시에 그릴 최대 단지 버블 수
  const REGION_LEVEL = 7;            // 이 레벨 이상(축소)이면 구 단위 버블 표시

  // 자치구 중심 좌표(구청 기준) - 저줌 지역 버블용
  const DISTRICT_CENTERS = {
    "11110": [37.5735, 126.9790], "11140": [37.5641, 126.9979],
    "11170": [37.5324, 126.9908], "11200": [37.5634, 127.0369],
    "11215": [37.5385, 127.0823], "11230": [37.5744, 127.0396],
    "11260": [37.6063, 127.0925], "11290": [37.5894, 127.0167],
    "11305": [37.6396, 127.0257], "11320": [37.6688, 127.0472],
    "11350": [37.6542, 127.0568], "11380": [37.6027, 126.9291],
    "11410": [37.5791, 126.9368], "11440": [37.5663, 126.9014],
    "11470": [37.5170, 126.8666], "11500": [37.5510, 126.8495],
    "11530": [37.4954, 126.8874], "11545": [37.4568, 126.8955],
    "11560": [37.5264, 126.8963], "11590": [37.5124, 126.9393],
    "11620": [37.4784, 126.9516], "11650": [37.4837, 127.0324],
    "11680": [37.5172, 127.0473], "11710": [37.5145, 127.1060],
    "11740": [37.5301, 127.1238],
  };

  const state = {
    meta: null, markers: [], map: null,
    overlays: [], selectedId: null, district: "", search: "", area: "",
    dealType: "sale",   // 지도 말풍선 기준: 'sale'(매매) | 'jeonse'(전세)
    // 상세 필터(8종). null/""/false = 미적용
    filters: { min: null, max: null, jr: "", drop: "", age: "",
               hh: "", far: "", n1y: "", peak: false },
    favorites: loadFavorites(), currentDetail: null, chartMode: "sale",
  };

  const $ = (id) => document.getElementById(id);
  const fmt = (v) => (window.SeoulCharts ? SeoulCharts.fmt(v) : v);

  // ── 초기화 ──────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    bindUI();
    await loadMeta();
    if (!window.KAKAO_JS_KEY) {
      showNotice("카카오 지도 키가 설정되지 않았습니다",
        "GitHub Secrets 또는 .env 의 KAKAO_JS_KEY 를 등록하면 지도가 표시됩니다.");
      return;
    }
    loadKakao(() => {
      initMap();
      loadMarkers();
    });
  }

  function bindUI() {
    $("district-select").addEventListener("change", (e) => {
      state.district = e.target.value; applyFilters(); panToDistrict();
    });
    $("search-input").addEventListener("input", debounce((e) => {
      state.search = e.target.value.trim(); applyFilters();
    }, 250));
    $("deal-type").addEventListener("change", (e) => {
      state.dealType = e.target.value;      // 매매/전세 → 지도 말풍선 가격 전환
      applyFilters();
    });
    $("area-filter").addEventListener("change", (e) => {
      state.area = e.target.value;
      applyFilters();                       // 지도 말풍선을 선택 평형 가격으로 갱신
      if (state.currentDetail) renderChart();
    });
    $("btn-rankings").addEventListener("click", showRankings);
    $("btn-favorites").addEventListener("click", showFavorites);
    bindFilterUI();
    $("panel-close").addEventListener("click", () => $("panel").classList.add("hidden"));
    $("modal-close").addEventListener("click", () => $("modal").classList.add("hidden"));
    $("modal").addEventListener("click", (e) => {
      if (e.target.id === "modal") $("modal").classList.add("hidden");
    });
    updateFavCount();
  }

  // ── 데이터 로드 ─────────────────────────────────────────────────────
  async function loadMeta() {
    try {
      state.meta = await fetchJSON(DATA + "meta.json");
    } catch {
      state.meta = null;
    }
    const sel = $("district-select");
    const list = (state.meta && state.meta.districts) || [];
    list.forEach((d) => {
      const o = document.createElement("option");
      o.value = d.lawd_cd;
      o.textContent = `${d.name} (${(d.sale_count || 0).toLocaleString()}건)`;
      sel.appendChild(o);
    });
    if (state.meta) {
      $("updated-label").textContent =
        "데이터 기준일: " + (state.meta.last_updated_display || "—");
    } else {
      $("updated-label").textContent = "데이터 수집 전";
    }
  }

  async function loadMarkers() {
    try {
      const j = await fetchJSON(DATA + "markers.json");
      state.markers = j.markers || [];
    } catch {
      state.markers = [];
    }
    renderMarkers();   // 마커가 없어도 구 단위 버블(meta 기반)은 표시
  }

  // ── 카카오 지도 ─────────────────────────────────────────────────────
  function loadKakao(cb) {
    const s = document.createElement("script");
    s.src = "https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey="
      + window.KAKAO_JS_KEY;
    s.onload = () => kakao.maps.load(cb);
    s.onerror = () => showNotice("지도를 불러오지 못했습니다",
      "카카오 개발자 콘솔에 이 도메인이 등록되어 있는지 확인하세요.");
    document.head.appendChild(s);
  }

  function initMap() {
    state.map = new kakao.maps.Map($("map"), {
      center: new kakao.maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng),
      level: 8,
    });
    // 이동/줌이 끝날 때마다 화면 안 버블만 다시 그린다
    kakao.maps.event.addListener(state.map, "idle", renderMarkers);
    // 창 크기 변경 시 지도 크기 재계산
    window.addEventListener("resize", debounce(() => {
      if (state.map) state.map.relayout();
    }, 200));
  }

  // ── 가격 버블 렌더링 (호갱노노 스타일 커스텀 오버레이) ──────────────
  function clearOverlays() {
    state.overlays.forEach((o) => o.setMap(null));
    state.overlays = [];
  }

  function renderMarkers() {
    if (!state.map) return;
    clearOverlays();

    // 축소 상태 + 필터 없음 → 구 단위 요약 버블
    // 구 요약 버블은 매매·전체평형·필터없음일 때만(전세/평형/상세필터 시 단지 버블로 전환)
    const zoomedOut = state.map.getLevel() >= REGION_LEVEL;
    if (zoomedOut && !state.district && !state.search && !state.area
        && state.dealType === "sale" && activeFilterCount() === 0) {
      renderRegionBubbles();
      hideNotice();
      return;
    }

    const bounds = state.map.getBounds();
    let visible = filteredMarkers().filter((m) =>
      markerPrice(m) && bounds.contain(new kakao.maps.LatLng(m.lat, m.lon)));
    if (visible.length > BUBBLE_CAP) {
      visible = visible.slice()
        .sort((a, b) => (markerPrice(b) || 0) - (markerPrice(a) || 0)).slice(0, BUBBLE_CAP);
    }
    visible.forEach((mk) => state.overlays.push(makeBubble(mk)));

    if (!visible.length && state.markers.length) {
      showNotice("조건에 맞는 단지가 없습니다", "검색어나 필터를 조정해 보세요.");
    } else if (!state.markers.length) {
      showNotice("아직 단지 좌표가 없습니다",
        "수집기(collect→geocode→export)를 실행하면 단지 버블이 표시됩니다.");
    } else {
      hideNotice();
    }
  }

  function makeBubble(mk) {
    const el = document.createElement("div");
    el.className = "price-bubble"
      + (mk.is_peak && state.dealType === "sale" ? " peak" : "")
      + (mk.id === state.selectedId ? " selected" : "");
    el.innerHTML =
      `<div class="pb-price">${bubblePrice(markerPrice(mk))}</div>` +
      `<div class="pb-name">${escapeHtml(mk.apt)}</div>`;
    el.addEventListener("click", () => {
      state.selectedId = mk.id;
      openComplex(mk);
      renderMarkers();
    });
    const ov = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(mk.lat, mk.lon),
      content: el, yAnchor: 1, clickable: true,
    });
    ov.setMap(state.map);
    return ov;
  }

  function renderRegionBubbles() {
    const list = (state.meta && state.meta.districts) || [];
    list.forEach((d) => {
      const c = DISTRICT_CENTERS[d.lawd_cd];
      if (!c) return;
      const el = document.createElement("div");
      el.className = "region-bubble";
      el.innerHTML =
        `<div class="rb-name">${d.name}</div>` +
        `<div class="rb-ppy">${d.ppy_median ? Math.round(d.ppy_median).toLocaleString() : "-"}</div>` +
        `<div class="rb-unit">만원/평</div>`;
      el.addEventListener("click", () => {
        state.map.setLevel(5);
        state.map.setCenter(new kakao.maps.LatLng(c[0], c[1]));
      });
      const ov = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(c[0], c[1]),
        content: el, yAnchor: .5, clickable: true,
      });
      ov.setMap(state.map);
      state.overlays.push(ov);
    });
  }

  // 거래유형(매매/전세) + 선택 평형에 따른 말풍선 가격
  function markerPrice(mk) {
    if (state.dealType === "jeonse") {
      return state.area ? (mk.jeonse_area ? mk.jeonse_area[state.area] : null) : mk.jeonse;
    }
    return state.area ? (mk.sale_area ? mk.sale_area[state.area] : null) : mk.sale;
  }

  function bubblePrice(manwon) {
    if (!manwon) return "-";
    if (manwon >= 10000) {
      const eok = manwon / 10000;
      const s = eok >= 100 ? Math.round(eok).toString()
        : (Math.round(eok * 10) / 10).toString();
      return s.replace(/\.0$/, "") + "억";
    }
    return manwon.toLocaleString() + "만";
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function filteredMarkers() {
    const f = state.filters;
    const nowYear = new Date().getFullYear();
    return state.markers.filter((m) => {
      if (state.district && m.lawd_cd !== state.district) return false;
      if (state.search && !m.apt.includes(state.search)) return false;

      // ── 상세 필터 (값 없는 단지는 해당 필터 사용 시 제외) ──
      if (f.min != null || f.max != null) {
        const p = markerPrice(m);            // 현재 매매/전세×평형 기준 가격(만원)
        if (!p) return false;
        if (f.min != null && p < f.min * 10000) return false;
        if (f.max != null && p > f.max * 10000) return false;
      }
      if (f.jr && !(m.jeonse_ratio >= +f.jr)) return false;
      if (f.drop && !(m.drop != null && m.drop <= -f.drop)) return false;
      if (f.peak && !m.is_peak) return false;
      if (f.age) {
        if (!m.by) return false;
        const age = nowYear - m.by;
        if (f.age === "new5" && age > 5) return false;
        if (f.age === "new10" && age > 10) return false;
        if (f.age === "mid" && (age <= 10 || age > 30)) return false;
        if (f.age === "old30" && age < 30) return false;
      }
      if (f.hh && !(m.hh >= +f.hh)) return false;
      if (f.far && !(m.far && m.far <= +f.far)) return false;
      if (f.n1y && !(m.n1y >= +f.n1y)) return false;
      return true;
    });
  }

  function activeFilterCount() {
    const f = state.filters;
    let n = 0;
    if (f.min != null || f.max != null) n++;
    ["jr", "drop", "age", "hh", "far", "n1y"].forEach((k) => { if (f[k]) n++; });
    if (f.peak) n++;
    return n;
  }

  function bindFilterUI() {
    const panel = $("filter-panel");
    $("btn-filter").addEventListener("click", () =>
      panel.classList.toggle("hidden"));
    $("f-close").addEventListener("click", () => panel.classList.add("hidden"));

    const onChange = () => {
      const f = state.filters;
      f.min = $("f-min").value === "" ? null : +$("f-min").value;
      f.max = $("f-max").value === "" ? null : +$("f-max").value;
      f.jr = $("f-jr").value;
      f.drop = $("f-drop").value ? +$("f-drop").value : "";
      f.age = $("f-age").value;
      f.hh = $("f-hh").value;
      f.far = $("f-far").value;
      f.n1y = $("f-n1y").value;
      f.peak = $("f-peak").checked;
      updateFilterBadge();
      applyFilters();
    };
    ["f-jr", "f-drop", "f-age", "f-hh", "f-far", "f-n1y", "f-peak"].forEach((id) =>
      $(id).addEventListener("change", onChange));
    ["f-min", "f-max"].forEach((id) =>
      $(id).addEventListener("input", debounce(onChange, 400)));

    $("f-reset").addEventListener("click", () => {
      ["f-min", "f-max"].forEach((id) => { $(id).value = ""; });
      ["f-jr", "f-drop", "f-age", "f-hh", "f-far", "f-n1y"].forEach((id) => {
        $(id).value = "";
      });
      $("f-peak").checked = false;
      onChange();
    });
  }

  function updateFilterBadge() {
    const n = activeFilterCount();
    const el = $("filter-count");
    el.textContent = n;
    el.classList.toggle("hidden", n === 0);
  }

  function applyFilters() {
    if (state.map) renderMarkers();
  }

  function panToDistrict() {
    if (!state.map) return;
    if (!state.district) {
      state.map.setCenter(new kakao.maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng));
      state.map.setLevel(8);
      return;
    }
    const ms = state.markers.filter((m) => m.lawd_cd === state.district);
    if (!ms.length) return;
    const bounds = new kakao.maps.LatLngBounds();
    ms.forEach((m) => bounds.extend(new kakao.maps.LatLng(m.lat, m.lon)));
    state.map.setBounds(bounds);
  }

  // ── 단지 상세 패널 ──────────────────────────────────────────────────
  async function openComplex(mk) {
    let detail;
    try {
      detail = await fetchJSON(`${DATA}complex/${mk.lawd_cd}/${mk.id}.json`);
    } catch {
      return;
    }
    state.currentDetail = Object.assign({}, mk, detail);
    renderPanel();
  }

  function renderPanel() {
    const d = state.currentDetail;
    const isFav = state.favorites.some((f) => f.id === d.id);
    const gongsi = latestGongsi(d);
    const el = $("panel-content");
    el.innerHTML = `
      <h2>${d.apt} ${d.is_peak ? '<span class="badge peak">신고가</span>' : ""}</h2>
      <div class="sub">${districtName(d.lawd_cd)}${d.umd ? " " + d.umd : ""} · ${buildYearText(d)}</div>
      <div class="price-cards">
        <div class="card"><div class="label">최근 매매 중앙값</div>
          <div class="value">${fmt(d.sale)}</div></div>
        <div class="card"><div class="label">평단가(만원/평)</div>
          <div class="value small">${d.ppy ? Math.round(d.ppy).toLocaleString() : "-"}</div></div>
        <div class="card"><div class="label">전세 중앙값</div>
          <div class="value small">${fmt(medianJeonse(d))}</div></div>
        <div class="card"><div class="label">전세가율</div>
          <div class="value small">${d.jeonse_ratio != null ? d.jeonse_ratio + "%" : "-"}</div></div>
        <div class="card"><div class="label">공시가격 ${gongsi ? "(" + gongsi.year + ")" : ""}</div>
          <div class="value small">${gongsi ? fmt(gongsi.price) : "미매칭"}</div></div>
        <div class="card"><div class="label">공시/실거래</div>
          <div class="value small">${gongsiRatio(d, gongsi)}</div></div>
      </div>

      ${buildingInfo(d)}

      <div class="btn-row">
        <button id="fav-toggle" class="${isFav ? "active" : ""}">
          ${isFav ? "★ 관심단지" : "☆ 관심단지"}</button>
        <button id="csv-btn">CSV 다운로드</button>
      </div>

      <div class="section-title">면적별 가격 추세</div>
      <div class="chart-tabs">
        <button data-mode="sale" class="${state.chartMode === "sale" ? "active" : ""}">매매</button>
        <button data-mode="jeonse" class="${state.chartMode === "jeonse" ? "active" : ""}">전세</button>
      </div>
      <div class="chart-wrap"><canvas id="detail-chart"></canvas></div>

      <div class="section-title">최근 매매 실거래</div>
      ${recentTxnsTable(d)}

      <div class="section-title">최근 전월세 실거래</div>
      ${recentRentsTable(d)}
    `;
    $("panel").classList.remove("hidden");
    $("fav-toggle").addEventListener("click", () => toggleFavorite(d));
    $("csv-btn").addEventListener("click", () => downloadCSV(d));
    el.querySelectorAll(".chart-tabs button").forEach((b) =>
      b.addEventListener("click", () => { state.chartMode = b.dataset.mode; renderPanel(); }));
    renderChart();
  }

  function renderChart() {
    const d = state.currentDetail;
    if (!d || !window.SeoulCharts) return;
    const series = state.chartMode === "sale" ? d.sale_series : d.jeonse_series;
    if (!series) return;
    let buckets = Object.keys(series);
    if (state.area && buckets.includes(state.area)) buckets = [state.area];
    const months = new Set();
    buckets.forEach((b) => series[b].forEach((p) => months.add(p.month)));
    const labels = [...months].sort();
    const colors = ["#ff7e00", "#2563eb", "#10b981", "#a855f7"];
    const datasets = buckets.map((b, i) => ({
      label: b, color: colors[i % colors.length],
      data: labels.map((m) => {
        const p = series[b].find((x) => x.month === m);
        return p ? p.median : null;
      }),
    }));
    SeoulCharts.line("detail-chart", labels, datasets);
  }

  function recentTxnsTable(d) {
    const rows = (d.recent_sales || []).slice(0, 20);
    if (!rows.length) return '<div class="empty">최근 매매 거래 없음</div>';
    // 신고가는 해제되지 않은 거래 기준
    const valid = rows.filter((r) => !r.canceled);
    const peak = valid.length ? Math.max(...valid.map((r) => r.amount)) : null;
    return `<table class="txns"><thead><tr>
        <th>계약일</th><th>면적</th><th>층</th><th>거래가</th></tr></thead><tbody>
      ${rows.map((r) => `<tr class="${r.canceled ? "canceled" : (peak !== null && r.amount >= peak ? "peak" : "")}">
        <td>${r.date}</td><td>${r.area}㎡</td><td>${r.floor || "-"}</td>
        <td>${fmt(r.amount)}${r.canceled ? ' <span class="cancel-badge">해제</span>' : ""}</td></tr>`).join("")}
      </tbody></table>`;
  }

  function recentRentsTable(d) {
    const rows = (d.recent_rents || []).slice(0, 20);
    if (!rows.length) return '<div class="empty">최근 전월세 거래 없음</div>';
    return `<table class="txns"><thead><tr>
        <th>계약일</th><th>구분</th><th>면적</th><th>층</th><th>보증금 / 월세</th></tr></thead><tbody>
      ${rows.map((r) => {
        const isJeonse = r.type === "jeonse";
        const badge = isJeonse
          ? '<span class="rent-badge jeonse">전세</span>'
          : '<span class="rent-badge wolse">월세</span>';
        const price = isJeonse ? fmt(r.deposit)
          : `${fmt(r.deposit)} / ${r.monthly.toLocaleString()}만`;
        return `<tr><td>${r.date}</td><td>${badge}</td>
          <td>${r.area}㎡</td><td>${r.floor || "-"}</td><td>${price}</td></tr>`;
      }).join("")}
      </tbody></table>`;
  }

  function buildYearText(d) {
    if (!d.build_year) return "전용면적별 실거래 기준";
    const now = new Date().getFullYear();
    const age = now - d.build_year;
    const ageTxt = age <= 0 ? "신축" : `${age}년차`;
    return `${d.build_year}년 준공 · ${ageTxt}`;
  }

  // 건축물대장 부가정보(세대수/용적률/건폐율). 값 하나라도 있으면 표시.
  function buildingInfo(d) {
    if (!d.households && !d.far && !d.bcr) return "";
    const cell = (label, val) =>
      `<div class="info-cell"><span class="info-label">${label}</span>` +
      `<span class="info-value">${val}</span></div>`;
    return `<div class="info-row">
      ${cell("세대수", d.households ? d.households.toLocaleString() + "세대" : "-")}
      ${cell("용적률", d.far ? d.far + "%" : "-")}
      ${cell("건폐율", d.bcr ? d.bcr + "%" : "-")}
    </div>`;
  }

  // ── 즐겨찾기 ────────────────────────────────────────────────────────
  function toggleFavorite(d) {
    const i = state.favorites.findIndex((f) => f.id === d.id);
    if (i >= 0) state.favorites.splice(i, 1);
    else state.favorites.push({ id: d.id, lawd_cd: d.lawd_cd, apt: d.apt });
    saveFavorites(state.favorites);
    updateFavCount();
    renderPanel();
  }

  function showFavorites() {
    const favs = state.favorites;
    let html = "<h2>관심단지 비교</h2>";
    if (!favs.length) {
      html += '<div class="empty">관심단지가 없습니다. 단지 상세에서 ☆를 눌러 추가하세요.</div>';
      openModal(html); return;
    }
    Promise.all(favs.map((f) =>
      fetchJSON(`${DATA}complex/${f.lawd_cd}/${f.id}.json`)
        .then((d) => ({ f, d })).catch(() => null)
    )).then((results) => {
      const valid = results.filter(Boolean);
      html += `<table class="rank-table"><thead><tr>
        <th>단지</th><th>자치구</th><th>최근매매</th><th>평단가</th><th>공시가격</th><th></th>
        </tr></thead><tbody>`;
      valid.forEach(({ f, d }) => {
        const g = latestGongsi(d);
        const lastSale = d.recent_sales && d.recent_sales[0];
        html += `<tr data-id="${f.id}" data-lawd="${f.lawd_cd}">
          <td>${f.apt}</td><td>${districtName(f.lawd_cd)}</td>
          <td>${lastSale ? fmt(lastSale.amount) : "-"}</td>
          <td>${ppyOf(d)}</td>
          <td>${g ? fmt(g.price) : "-"}</td>
          <td>✕</td></tr>`;
      });
      html += "</tbody></table>";
      openModal(html);
      document.querySelectorAll("#modal-content tr[data-id]").forEach((tr) => {
        tr.querySelector("td:last-child").addEventListener("click", (e) => {
          e.stopPropagation();
          const id = +tr.dataset.id;
          state.favorites = state.favorites.filter((x) => x.id !== id);
          saveFavorites(state.favorites); updateFavCount(); showFavorites();
        });
      });
    });
  }

  // ── 구별 랭킹 + 부동산원 지수 ───────────────────────────────────────
  function showRankings() {
    const ranks = (state.meta && state.meta.rankings) || [];
    let html = "<h2>자치구 평단가 랭킹</h2>";
    if (!ranks.length) {
      html += '<div class="empty">랭킹 데이터가 아직 없습니다.</div>';
      openModal(html); return;
    }
    html += `<table class="rank-table"><thead><tr>
      <th>#</th><th>자치구</th><th>평단가(만원/평)</th><th>6개월 변동</th><th>거래건수</th>
      </tr></thead><tbody>`;
    ranks.forEach((r, i) => {
      const chg = r.change_6m;
      const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
      html += `<tr data-lawd="${r.lawd_cd}">
        <td>${i + 1}</td><td>${r.name}</td>
        <td>${r.ppy_median ? Math.round(r.ppy_median).toLocaleString() : "-"}</td>
        <td class="${cls}">${chg != null ? (chg > 0 ? "+" : "") + chg + "%" : "-"}</td>
        <td>${(r.sale_count || 0).toLocaleString()}</td></tr>`;
    });
    html += "</tbody></table>";
    html += '<div class="section-title">부동산원 가격지수 (서울)</div>' +
            '<div class="chart-wrap"><canvas id="reb-chart"></canvas></div>';
    openModal(html);
    document.querySelectorAll("#modal-content tr[data-lawd]").forEach((tr) =>
      tr.addEventListener("click", () => {
        state.district = tr.dataset.lawd;
        $("district-select").value = state.district;
        applyFilters(); panToDistrict();
        $("modal").classList.add("hidden");
      }));
    renderRebChart();
  }

  async function renderRebChart() {
    let reb;
    try { reb = await fetchJSON(DATA + "reb/seoul_index.json"); } catch { return; }
    const stats = Object.keys(reb || {});
    if (!stats.length || !window.SeoulCharts) return;
    const colors = ["#ff7e00", "#2563eb"];
    let labels = [];
    const datasets = [];
    stats.forEach((stat, i) => {
      const regions = reb[stat];
      const seoul = regions["서울"] || regions[Object.keys(regions)[0]] || [];
      if (seoul.length > labels.length) labels = seoul.map((p) => p.period);
      datasets.push({ label: stat, color: colors[i % colors.length],
        data: seoul.map((p) => p.value) });
    });
    SeoulCharts.line("reb-chart", labels, datasets);
  }

  // ── CSV ─────────────────────────────────────────────────────────────
  function downloadCSV(d) {
    const rows = d.recent_sales || [];
    const header = "계약일,단지,전용면적(㎡),층,거래금액(만원)\n";
    const body = rows.map((r) =>
      `${r.date},${d.apt},${r.area},${r.floor || ""},${r.amount}`).join("\n");
    const blob = new Blob(["﻿" + header + body], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${d.apt}_실거래.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  // ── 유틸 ────────────────────────────────────────────────────────────
  function latestGongsi(d) {
    if (!d.gongsi || !d.gongsi.length) return null;
    return d.gongsi.slice().sort((a, b) => b.year - a.year)[0];
  }
  function gongsiRatio(d, g) {
    if (!g || !d.sale) return "-";
    return Math.round(g.price / d.sale * 100) + "%";
  }
  function medianJeonse(d) {
    const s = d.jeonse_series || {};
    const all = [];
    Object.values(s).forEach((arr) => arr.forEach((p) => p.median && all.push(p.median)));
    if (!all.length) return null;
    all.sort((a, b) => a - b);
    return all[Math.floor(all.length / 2)];
  }
  function ppyOf(d) {
    const last = d.recent_sales && d.recent_sales[0];
    if (!last || !last.area) return "-";
    const py = last.area * (1 / 3.305785);
    return Math.round(last.amount / py).toLocaleString();
  }
  function districtName(lawd) {
    const d = (state.meta && state.meta.districts || []).find((x) => x.lawd_cd === lawd);
    return d ? d.name : lawd;
  }
  function openModal(html) {
    $("modal-content").innerHTML = html;
    $("modal").classList.remove("hidden");
  }
  function showNotice(title, msg) {
    const n = $("map-notice");
    n.innerHTML = `<h3>${title}</h3><p>${msg}</p>`;
    n.classList.remove("hidden");
  }
  function hideNotice() { $("map-notice").classList.add("hidden"); }
  function updateFavCount() { $("fav-count").textContent = state.favorites.length; }
  function loadFavorites() {
    try { return JSON.parse(localStorage.getItem("seoul_apt_favs") || "[]"); }
    catch { return []; }
  }
  function saveFavorites(f) { localStorage.setItem("seoul_apt_favs", JSON.stringify(f)); }
  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  function debounce(fn, ms) {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
})();
