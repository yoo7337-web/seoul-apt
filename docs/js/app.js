/* 서울 아파트 시세 지도 - 메인 앱 */
(function () {
  "use strict";

  const DATA = "data/";
  const SEOUL_CENTER = { lat: 37.5665, lng: 126.978 };
  const BUBBLE_CAP = 250;            // 화면에 동시에 그릴 최대 단지 버블 수
  const REGION_LEVEL = 7;            // 이 레벨 이상(축소)이면 구 단위 버블 표시

  // 필터 슬라이더 정의(듀얼 레인지). hi==max 이면 상한 없음(N↑), lo==min 이면 하한 없음
  const M2_PER_PY = 3.305785;       // 1평 = 3.305785㎡
  const F_SLIDERS = [
    { key: "area", label: "평형", min: 0, max: 80, step: 1, u: "평",
      ticks: ["0", "20", "40", "60", "80+"] },
    { key: "price", label: "가격", min: 0, max: 40, step: 0.5, u: "억",
      ticks: ["0", "5억", "10억", "20억", "40억+"] },
    { key: "age", label: "입주년차", min: 0, max: 30, step: 1, u: "년",
      ticks: ["0", "10년", "20년", "30년+"] },
    { key: "hh", label: "세대수", min: 0, max: 5000, step: 100, u: "세대",
      ticks: ["0", "1000", "3000", "5000+"] },
    { key: "jr", label: "전세가율", min: 0, max: 200, step: 5, u: "%",
      ticks: ["0", "50%", "100%", "150%", "200%+"] },
    { key: "gap", label: "갭가격", min: 0, max: 15, step: 0.5, u: "억",
      ticks: ["0", "3억", "6억", "9억", "15억+"] },
    { key: "far", label: "용적률", min: 0, max: 600, step: 10, u: "%",
      ticks: ["0", "200%", "400%", "600%+"] },
    { key: "n1y", label: "거래활발도(1년)", min: 0, max: 50, step: 1, u: "건",
      ticks: ["0", "10건", "30건", "50건+"] },
    { key: "drop", label: "고점대비 하락", min: 0, max: 50, step: 5, u: "%",
      ticks: ["0", "10%", "20%", "30%", "50%+"] },
  ];
  const F_CFG = Object.fromEntries(F_SLIDERS.map((s) => [s.key, s]));

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
    overlays: [], selectedId: null, districts: new Set(), search: "", area: "",
    dealType: "sale",   // 지도 말풍선 기준: 'sale'(매매) | 'jeonse'(전세)
    // 슬라이더 범위 {lo,hi} + 토글. lo==min && hi==max 이면 미적용
    range: Object.fromEntries(F_SLIDERS.map((s) => [s.key, { lo: s.min, hi: s.max }])),
    minusGap: false, peak: false,
    favorites: loadFavorites(), currentDetail: null, chartMode: "sale",
    detailArea: "",   // 상세 패널 면적(평형) 선택 ("" = 전체)
    favDistricts: loadFavDistricts(),   // 관심구(lawd_cd Set)
  };

  const BUCKET_ORDER = ["~60㎡", "60~85㎡", "85~135㎡", "135㎡~"];
  function areaBucket(area) {
    if (area < 60) return "~60㎡";
    if (area < 85) return "60~85㎡";
    if (area < 135) return "85~135㎡";
    return "135㎡~";
  }
  function detailBuckets(d) {   // 이 단지가 보유한 면적 버킷(표준 순서)
    const s = new Set([...Object.keys(d.sale_series || {}),
                       ...Object.keys(d.jeonse_series || {})]);
    return BUCKET_ORDER.filter((b) => s.has(b));
  }

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
      const v = e.target.value;   // 드롭다운 = 단일 선택 shortcut(공유 선택 갱신)
      setSelectedDistricts(v ? new Set([v]) : new Set());
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
    $("btn-favorites").addEventListener("click", showFavorites);
    $("btn-dashboard").addEventListener("click", toggleDashboard);
    $("dash-close").addEventListener("click", () => toggleDashboard(false));
    bindDashResizer();
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
    if (zoomedOut && !state.districts.size && !state.search && !state.area
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
    const info = markerInfo(mk);
    el.className = "price-bubble"
      + (mk.is_peak && state.dealType === "sale" ? " peak" : "")
      + (info && info.stale ? " stale" : "")
      + (mk.id === state.selectedId ? " selected" : "");
    const pyTag = (info && info.py) ? `<span class="pb-py">${info.py}평</span>` : "";
    const staleIcon = (info && info.stale)
      ? `<span class="pb-stale" title="최근 1년 내 실거래 없음 · 오래된 가격">🕒</span>` : "";
    el.innerHTML =
      `<div class="pb-price">${staleIcon}${bubblePrice(info ? info.price : null)}${pyTag}</div>` +
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
      const isFav = state.favDistricts.has(d.lawd_cd);
      const el = document.createElement("div");
      el.className = "region-bubble" + (isFav ? " fav" : "");
      el.innerHTML =
        (isFav ? '<span class="rb-star">★</span>' : "") +
        `<div class="rb-name">${d.name}</div>` +
        `<div class="rb-ppy">${d.ppy_median ? Math.round(d.ppy_median).toLocaleString() : "-"}</div>` +
        `<div class="rb-unit">만원/평</div>`;
      el.addEventListener("click", () => {
        state.map.setLevel(5);
        state.map.setCenter(new kakao.maps.LatLng(c[0], c[1]));
      });
      el.addEventListener("contextmenu", (e) => {   // 우클릭 = 관심구 토글
        e.preventDefault();
        toggleFavDistrict(d.lawd_cd, d.name);
      });
      el.title = "우클릭: 관심구 " + (isFav ? "해제" : "설정");
      const ov = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(c[0], c[1]),
        content: el, yAnchor: .5, clickable: true,
        zIndex: isFav ? 10 : 1,   // 관심구는 겹쳐도 앞으로
      });
      ov.setMap(state.map);
      state.overlays.push(ov);
    });
  }

  // 거래유형(매매/전세)+평형에 따른 대표 거래 정보.
  // 전체 평형이면 단지 대표 평형(rep/jrep)의 최근가, 특정 평형이면 그 평형의 최근가.
  // (전 면적 혼합 중앙값 대신 '어떤 평형의 가격'인지 명확히)
  function markerInfo(mk) {
    const jeonse = state.dealType === "jeonse";
    const byArea = jeonse ? mk.jeonse_area : mk.sale_area;
    const bucket = state.area || (jeonse ? mk.jrep : mk.rep);
    const o = (byArea && bucket) ? byArea[bucket] : null;
    return o ? { price: o.p, py: o.py, stale: !!o.s, bucket } : null;
  }
  function markerPrice(mk) {
    const info = markerInfo(mk);
    return info ? info.price : null;
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
    const R = state.range, nowYear = new Date().getFullYear();
    const active = (k) => R[k].lo > F_CFG[k].min || R[k].hi < F_CFG[k].max;
    const inR = (k, v) => {   // 값이 범위 내인지(값 없으면 제외)
      const r = R[k], c = F_CFG[k];
      if (v == null) return false;
      if (r.lo > c.min && v < r.lo) return false;
      if (r.hi < c.max && v > r.hi) return false;
      return true;
    };
    return state.markers.filter((m) => {
      if (state.districts.size && !state.districts.has(m.lawd_cd)) return false;
      if (state.search && !m.apt.includes(state.search)) return false;

      // 평형(단지 면적범위 ㎡→평, 슬라이더 구간과 겹치면 표시)
      if (active("area")) {
        if (m.am == null || m.ax == null) return false;
        const r = R.area, cxLo = m.am / M2_PER_PY, cxHi = m.ax / M2_PER_PY;
        if (r.lo > 0 && cxHi < r.lo) return false;
        if (r.hi < 80 && cxLo > r.hi) return false;
      }
      if (active("price")) {
        const p = markerPrice(m);
        if (!inR("price", p == null ? null : p / 10000)) return false;   // 억
      }
      if (active("age") && !inR("age", m.by ? nowYear - m.by : null)) return false;
      if (active("hh") && !inR("hh", m.hh)) return false;
      if (active("jr") && !inR("jr", m.jeonse_ratio)) return false;
      if (active("far") && !inR("far", m.far)) return false;
      if (active("n1y") && !inR("n1y", m.n1y)) return false;
      // 갭가격(억): 마이너스갭 토글 우선
      if (state.minusGap) {
        if (m.sale == null || m.jeonse == null || (m.sale - m.jeonse) >= 0) return false;
      } else if (active("gap")) {
        const g = (m.sale != null && m.jeonse != null) ? (m.sale - m.jeonse) / 10000 : null;
        if (!inR("gap", g)) return false;
      }
      if (state.peak && !m.is_peak) return false;
      // 고점대비 하락(%): drop은 음수(하락)/0(신고가) → 하락폭 -drop 으로 비교
      if (active("drop") && !inR("drop", m.drop == null ? null : -m.drop)) return false;
      return true;
    });
  }

  function activeFilterCount() {
    let n = 0;
    F_SLIDERS.forEach((s) => {
      if (s.key === "gap" && state.minusGap) return;   // 마이너스갭이 갭슬라이더 대체
      if (state.range[s.key].lo > s.min || state.range[s.key].hi < s.max) n++;
    });
    if (state.minusGap) n++;
    if (state.peak) n++;
    return n;
  }

  // ── 필터 패널(슬라이더 생성 + 바인딩) ───────────────────────────────
  function fmtValNum(s, v) {
    return (s.key === "hh" ? v.toLocaleString() : v) + s.u;
  }
  function paintRange(s) {
    const r = state.range[s.key];
    const pct = (v) => ((v - s.min) / (s.max - s.min)) * 100;
    const fill = $("rfill-" + s.key);
    if (fill) { fill.style.left = pct(r.lo) + "%"; fill.style.width = (pct(r.hi) - pct(r.lo)) + "%"; }
    const val = $("fv-" + s.key);
    if (val) {
      const full = r.lo <= s.min && r.hi >= s.max;
      val.textContent = full ? "전체"
        : `${fmtValNum(s, r.lo)} ~ ${fmtValNum(s, r.hi)}${r.hi >= s.max ? "↑" : ""}`;
    }
  }
  function rangeHtml(s) {
    const r = state.range[s.key];
    return `<div class="fs-item">
      <div class="fs-head"><span class="fs-label">${s.label}</span>
        <span class="fs-val" id="fv-${s.key}"></span></div>
      <div class="range"><div class="rtrack"></div><div class="rfill" id="rfill-${s.key}"></div>
        <input type="range" id="rlo-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}" value="${r.lo}">
        <input type="range" id="rhi-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}" value="${r.hi}">
      </div>
      <div class="range-ticks">${s.ticks.map((t) => `<span>${t}</span>`).join("")}</div>
    </div>`;
  }
  function bindRange(s) {
    const lo = $("rlo-" + s.key), hi = $("rhi-" + s.key);
    const upd = (commit) => {
      let a = +lo.value, b = +hi.value;
      if (a > b) {   // 교차 방지
        if (document.activeElement === lo) { b = a; hi.value = b; }
        else { a = b; lo.value = a; }
      }
      state.range[s.key] = { lo: a, hi: b };
      paintRange(s);
      if (commit) onFilterChange();
    };
    lo.addEventListener("input", () => upd(false));
    hi.addEventListener("input", () => upd(false));
    lo.addEventListener("change", () => upd(true));
    hi.addEventListener("change", () => upd(true));
    paintRange(s);
  }
  function buildFilterUI() {
    let html = F_SLIDERS.map(rangeHtml).join("");
    html += `<label class="fs-toggle"><input type="checkbox" id="f-minusgap"> 마이너스 갭 보기 (전세>매매)</label>`;
    html += `<label class="fs-toggle"><input type="checkbox" id="f-peak"> 신고가 단지만</label>`;
    $("filter-body").innerHTML = html;
    F_SLIDERS.forEach(bindRange);
    $("f-minusgap").addEventListener("change", (e) => { state.minusGap = e.target.checked; onFilterChange(); });
    $("f-peak").addEventListener("change", (e) => { state.peak = e.target.checked; onFilterChange(); });
  }
  function resetFilters() {
    F_SLIDERS.forEach((s) => {
      state.range[s.key] = { lo: s.min, hi: s.max };
      const lo = $("rlo-" + s.key), hi = $("rhi-" + s.key);
      if (lo) { lo.value = s.min; hi.value = s.max; }
      paintRange(s);
    });
    state.minusGap = state.peak = false;
    if ($("f-minusgap")) $("f-minusgap").checked = false;
    if ($("f-peak")) $("f-peak").checked = false;
    onFilterChange();
  }
  function onFilterChange() { updateFilterBadge(); applyFilters(); }

  function toggleFilter(force) {
    const open = typeof force === "boolean"
      ? force : !document.body.classList.contains("filter-open");
    document.body.classList.toggle("filter-open", open);
    $("filter-panel").classList.toggle("hidden", !open);
    setTimeout(() => { if (state.map) state.map.relayout(); }, 80);
  }

  function bindFilterUI() {
    buildFilterUI();
    $("btn-filter").addEventListener("click", () => toggleFilter());
    $("filter-close").addEventListener("click", () => toggleFilter(false));
    $("f-close").addEventListener("click", () => toggleFilter(false));
    $("f-reset").addEventListener("click", resetFilters);
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

  // 대시보드 분할 패널 토글 (지도는 오른쪽으로 밀려 함께 표시)
  function toggleDashboard(force) {
    const open = typeof force === "boolean"
      ? force : !document.body.classList.contains("dash-open");
    document.body.classList.toggle("dash-open", open);
    $("dash-panel").classList.toggle("hidden", !open);
    $("dash-resizer").classList.toggle("hidden", !open);
    if (open && window.SeoulDash) SeoulDash.open();
    // 지도 컨테이너 크기가 바뀌었으니 카카오 지도 재계산
    setTimeout(() => { if (state.map) state.map.relayout(); }, 80);
  }

  // 대시보드 패널 너비를 드래그로 조절
  const DASH_MIN = 320;
  function setDashWidth(px, relayout) {
    const max = Math.round(window.innerWidth * 0.8);
    px = Math.max(DASH_MIN, Math.min(Math.round(px), max));
    document.documentElement.style.setProperty("--dash-w", px + "px");
    if (relayout && state.map) state.map.relayout();
    return px;
  }
  function bindDashResizer() {
    const saved = parseInt(localStorage.getItem("seoul_apt_dash_w"), 10);
    if (saved) setDashWidth(saved, false);
    const rz = $("dash-resizer");
    let dragging = false, raf = 0;
    rz.addEventListener("pointerdown", (e) => {
      dragging = true; rz.setPointerCapture(e.pointerId);
      document.body.classList.add("resizing"); e.preventDefault();
    });
    rz.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const x = e.clientX;
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; setDashWidth(x, true); });
    });
    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      try { rz.releasePointerCapture(e.pointerId); } catch (_) {}
      document.body.classList.remove("resizing");
      const w = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue("--dash-w"), 10);
      if (w) localStorage.setItem("seoul_apt_dash_w", w);
      if (state.map) state.map.relayout();
    };
    rz.addEventListener("pointerup", end);
    rz.addEventListener("pointercancel", end);
  }

  function panToSelected() {
    if (!state.map) return;
    if (!state.districts.size) {
      state.map.setCenter(new kakao.maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng));
      state.map.setLevel(8);
      return;
    }
    const ms = state.markers.filter((m) => state.districts.has(m.lawd_cd));
    if (!ms.length) return;
    const bounds = new kakao.maps.LatLngBounds();
    ms.forEach((m) => bounds.extend(new kakao.maps.LatLng(m.lat, m.lon)));
    state.map.setBounds(bounds);
  }

  // ── 구 선택 공유(랭킹·추이·지도 연동) ───────────────────────────────
  function setSelectedDistricts(set) {
    state.districts = new Set(set);
    const sel = $("district-select");
    if (sel) sel.value = state.districts.size === 1 ? [...state.districts][0] : "";
    applyFilters();
    panToSelected();
    if (window.SeoulMap.onChange) window.SeoulMap.onChange(new Set(state.districts));
  }

  function focusComplex(id) {
    const mk = state.markers.find((m) => m.id === id);
    if (!mk || !state.map) return false;
    state.map.setLevel(4);
    state.map.setCenter(new kakao.maps.LatLng(mk.lat, mk.lon));
    state.selectedId = id;
    openComplex(mk);
    renderMarkers();
    return true;
  }

  // 대시보드(dashboard.js)에서 지도를 제어하는 공유 API
  window.SeoulMap = {
    getSelected: () => new Set(state.districts),
    setSelected: (set) => setSelectedDistricts(set),
    toggle: (lawd) => {
      const s = new Set(state.districts);
      s.has(lawd) ? s.delete(lawd) : s.add(lawd);
      setSelectedDistricts(s);
    },
    selectAll: () => setSelectedDistricts(
      new Set((state.meta && state.meta.districts || []).map((d) => d.lawd_cd))),
    clear: () => setSelectedDistricts(new Set()),
    focusComplex,
    onChange: null,   // dashboard.js 가 등록: (Set) => void
  };

  // ── 단지 상세 패널 ──────────────────────────────────────────────────
  async function openComplex(mk) {
    let detail;
    try {
      detail = await fetchJSON(`${DATA}complex/${mk.lawd_cd}/${mk.id}.json`);
    } catch {
      return;
    }
    state.currentDetail = Object.assign({}, mk, detail);
    // 상세 면적 선택: 전역 평형 필터를 상속(해당 단지에 있으면), 없으면 전체
    const bks = detailBuckets(state.currentDetail);
    state.detailArea = (state.area && bks.includes(state.area)) ? state.area : "";
    renderPanel();
  }

  // 상세 패널: 선택 평형(없으면 대표 평형) 기준 최근 매매/전세가
  function detailInfo(d, jeonse) {
    const byArea = jeonse ? d.jeonse_area : d.sale_area;
    const bucket = state.detailArea || (jeonse ? d.jrep : d.rep);
    const o = (byArea && bucket) ? byArea[bucket] : null;
    return o ? { price: o.p, py: o.py, stale: !!o.s } : null;
  }
  const cardArea = (info) => (info && info.py ? ` · ${info.py}평` : "");
  const staleTag = (info) =>
    (info && info.stale ? ' <span class="stale-tag">1년+</span>' : "");

  function renderPanel() {
    const d = state.currentDetail;
    const si = detailInfo(d, false), ji = detailInfo(d, true);
    const isFav = state.favorites.some((f) => f.id === d.id);
    const gongsi = latestGongsi(d);
    const el = $("panel-content");
    el.innerHTML = `
      <h2>${d.apt} ${d.is_peak ? '<span class="badge peak">신고가</span>' : ""}</h2>
      <div class="sub">${districtName(d.lawd_cd)}${d.umd ? " " + d.umd : ""} · ${buildYearText(d)}</div>
      <div class="price-cards">
        <div class="card"><div class="label">최근 매매${cardArea(si)}</div>
          <div class="value">${si ? fmt(si.price) : "-"}${staleTag(si)}</div></div>
        <div class="card"><div class="label">평단가(만원/평)</div>
          <div class="value small">${d.ppy ? Math.round(d.ppy).toLocaleString() : "-"}</div></div>
        <div class="card"><div class="label">최근 전세${cardArea(ji)}</div>
          <div class="value small">${ji ? fmt(ji.price) : "-"}${staleTag(ji)}</div></div>
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
      ${areaTabs(d)}
      <div class="chart-wrap"><canvas id="detail-chart"></canvas></div>

      <div class="section-title">최근 매매 실거래${areaLabel()}</div>
      ${recentTxnsTable(d)}

      <div class="section-title">최근 전월세 실거래${areaLabel()}</div>
      ${recentRentsTable(d)}
    `;
    $("panel").classList.remove("hidden");
    $("fav-toggle").addEventListener("click", () => toggleFavorite(d));
    $("csv-btn").addEventListener("click", () => downloadCSV(d));
    el.querySelectorAll(".chart-tabs button").forEach((b) =>
      b.addEventListener("click", () => { state.chartMode = b.dataset.mode; renderPanel(); }));
    el.querySelectorAll("[data-area]").forEach((b) =>
      b.addEventListener("click", () => { state.detailArea = b.dataset.area; renderPanel(); }));
    renderChart();
  }

  // 면적(평형) 선택 칩. 이 단지가 보유한 버킷만 + 전체
  function areaTabs(d) {
    const bks = detailBuckets(d);
    if (bks.length <= 1) return "";   // 버킷이 하나뿐이면 선택 불필요
    const chip = (val, txt) =>
      `<button class="d-chip${state.detailArea === val ? " on" : ""}" data-area="${val}">${txt}</button>`;
    return `<div class="area-tabs">${chip("", "전체")}${bks.map((b) => chip(b, b)).join("")}</div>`;
  }
  function areaLabel() {
    return state.detailArea ? ` <span class="area-tag">${state.detailArea}</span>` : "";
  }

  function renderChart() {
    const d = state.currentDetail;
    if (!d || !window.SeoulCharts) return;
    const series = state.chartMode === "sale" ? d.sale_series : d.jeonse_series;
    if (!series) return;
    let buckets = Object.keys(series);
    if (state.detailArea && buckets.includes(state.detailArea)) buckets = [state.detailArea];
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
    let rows = d.recent_sales || [];
    if (state.detailArea) rows = rows.filter((r) => areaBucket(r.area) === state.detailArea);
    rows = rows.slice(0, 20);
    if (!rows.length) return '<div class="empty">해당 면적 매매 거래 없음</div>';
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
    let rows = d.recent_rents || [];
    if (state.detailArea) rows = rows.filter((r) => areaBucket(r.area) === state.detailArea);
    rows = rows.slice(0, 20);
    if (!rows.length) return '<div class="empty">해당 면적 전월세 거래 없음</div>';
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

  // 관심(관심구 + 관심단지) 통합 모달
  function showFavorites() {
    // ── 관심구 섹션(동기) ──
    const rankByCd = {};
    (state.meta && state.meta.rankings || []).forEach((r) => { rankByCd[r.lawd_cd] = r; });
    let dHtml = '<div class="fav-sec-title">⭐ 관심구</div>';
    const favD = [...state.favDistricts];
    if (!favD.length) {
      dHtml += '<div class="empty">지도에서 구 버블을 우클릭해 관심구를 추가하세요.</div>';
    } else {
      dHtml += `<table class="rank-table"><thead><tr>
        <th>자치구</th><th>평단가</th><th>6개월</th><th></th></tr></thead><tbody>`;
      favD.forEach((cd) => {
        const r = rankByCd[cd] || {};
        const chg = r.change_6m;
        const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
        dHtml += `<tr class="fav-d-row" data-lawd="${cd}">
          <td>★ ${districtName(cd)}</td>
          <td>${r.ppy_median ? Math.round(r.ppy_median).toLocaleString() : "-"}</td>
          <td class="${cls}">${chg != null ? (chg > 0 ? "+" : "") + chg + "%" : "-"}</td>
          <td class="fav-del" data-kind="d" data-lawd="${cd}">✕</td></tr>`;
      });
      dHtml += "</tbody></table>";
    }

    const finish = (cHtml) => {
      openModal(`<h2>★ 관심</h2>${dHtml}<div class="fav-sec-title">🏢 관심단지</div>${cHtml}`);
      bindFavModal();
    };

    // ── 관심단지 섹션(비동기) ──
    const favs = state.favorites;
    if (!favs.length) {
      finish('<div class="empty">단지 상세에서 ☆를 눌러 추가하세요.</div>');
      return;
    }
    Promise.all(favs.map((f) =>
      fetchJSON(`${DATA}complex/${f.lawd_cd}/${f.id}.json`)
        .then((d) => ({ f, d })).catch(() => null)
    )).then((results) => {
      const valid = results.filter(Boolean);
      let c = `<table class="rank-table"><thead><tr>
        <th>단지</th><th>자치구</th><th>최근매매</th><th>평단가</th><th></th>
        </tr></thead><tbody>`;
      valid.forEach(({ f, d }) => {
        const lastSale = d.recent_sales && d.recent_sales[0];
        c += `<tr class="fav-c-row" data-id="${f.id}" data-lawd="${f.lawd_cd}">
          <td>${f.apt}</td><td>${districtName(f.lawd_cd)}</td>
          <td>${lastSale ? fmt(lastSale.amount) : "-"}</td>
          <td>${ppyOf(d)}</td>
          <td class="fav-del" data-kind="c" data-id="${f.id}">✕</td></tr>`;
      });
      finish(c + "</tbody></table>");
    });
  }

  function bindFavModal() {
    // 관심구 행 클릭 → 지도에서 그 구 선택 + 모달 닫기
    document.querySelectorAll("#modal-content tr.fav-d-row").forEach((tr) =>
      tr.addEventListener("click", () => {
        setSelectedDistricts(new Set([tr.dataset.lawd]));
        $("modal").classList.add("hidden");
      }));
    // 관심단지 행 클릭 → 그 단지 지도 표시
    document.querySelectorAll("#modal-content tr.fav-c-row").forEach((tr) =>
      tr.addEventListener("click", () => {
        $("modal").classList.add("hidden");
        focusComplex(+tr.dataset.id);
      }));
    // ✕ 해제(구/단지)
    document.querySelectorAll("#modal-content .fav-del").forEach((td) =>
      td.addEventListener("click", (e) => {
        e.stopPropagation();
        if (td.dataset.kind === "d") {
          state.favDistricts.delete(td.dataset.lawd);
          localStorage.setItem("seoul_apt_fav_districts", JSON.stringify([...state.favDistricts]));
          renderMarkers();
          if (window.SeoulDash && SeoulDash.refresh) SeoulDash.refresh();
        } else {
          state.favorites = state.favorites.filter((x) => x.id !== +td.dataset.id);
          saveFavorites(state.favorites);
        }
        updateFavCount();
        showFavorites();
      }));
  }

  // ── 구별 랭킹 + 부동산원 지수 ───────────────────────────────────────
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
  function updateFavCount() {
    $("fav-count").textContent = state.favDistricts.size + state.favorites.length;
  }
  function loadFavorites() {
    try { return JSON.parse(localStorage.getItem("seoul_apt_favs") || "[]"); }
    catch { return []; }
  }
  function saveFavorites(f) { localStorage.setItem("seoul_apt_favs", JSON.stringify(f)); }

  // ── 관심구 ──────────────────────────────────────────────────────────
  function loadFavDistricts() {
    try { return new Set(JSON.parse(localStorage.getItem("seoul_apt_fav_districts") || "[]")); }
    catch { return new Set(); }
  }
  function toggleFavDistrict(lawd, name) {
    const on = !state.favDistricts.has(lawd);
    on ? state.favDistricts.add(lawd) : state.favDistricts.delete(lawd);
    localStorage.setItem("seoul_apt_fav_districts", JSON.stringify([...state.favDistricts]));
    toast(`${name} 관심구 ${on ? "설정 ★" : "해제"}`);
    updateFavCount();
    renderMarkers();
    if (window.SeoulDash && SeoulDash.refresh) SeoulDash.refresh();   // 랭킹 별표 갱신
  }

  let toastTimer;
  function toast(msg) {
    let el = $("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; document.body.appendChild(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1600);
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });  // 매일 갱신 데이터 → 항상 최신
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  function debounce(fn, ms) {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
})();
