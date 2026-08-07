/* 서울 아파트 시세 지도 - 메인 앱 */
(function () {
  "use strict";

  const DATA = "data/";
  const SEOUL_CENTER = { lat: 37.5665, lng: 126.978 };
  const BUBBLE_CAP = 250;            // 화면에 동시에 그릴 최대 단지 버블 수
  const REGION_LEVEL = 7;            // 이 레벨 이상(축소)이면 구 단위 버블 표시

  // 필터 슬라이더 정의(듀얼 레인지). hi==max 이면 상한 없음(N↑), lo==min 이면 하한 없음
  // ticks: [값, 라벨] - 라벨을 실제 값 위치에 배치해 슬라이더 바와 눈금을 일치시킨다.
  const M2_PER_PY = 3.305785;       // 1평 = 3.305785㎡
  const F_SLIDERS = [
    { key: "area", label: "평형", min: 0, max: 80, step: 1, u: "평",
      ticks: [[0, "0"], [20, "20"], [40, "40"], [60, "60"], [80, "80+"]] },
    { key: "price", label: "가격", min: 0, max: 40, step: 0.5, u: "억",
      ticks: [[0, "0"], [5, "5억"], [10, "10억"], [20, "20억"], [40, "40억+"]] },
    { key: "age", label: "입주년차", min: 0, max: 30, step: 1, u: "년",
      ticks: [[0, "0"], [10, "10년"], [20, "20년"], [30, "30년+"]] },
    { key: "hh", label: "세대수", min: 0, max: 5000, step: 100, u: "세대",
      ticks: [[0, "0"], [1000, "1000"], [3000, "3000"], [5000, "5000+"]] },
    { key: "jr", label: "전세가율", min: 0, max: 200, step: 5, u: "%",
      ticks: [[0, "0"], [50, "50%"], [100, "100%"], [150, "150%"], [200, "200%+"]] },
    { key: "gap", label: "갭가격", min: 0, max: 15, step: 0.5, u: "억",
      ticks: [[0, "0"], [3, "3억"], [6, "6억"], [9, "9억"], [15, "15억+"]] },
    { key: "far", label: "용적률", min: 0, max: 600, step: 10, u: "%",
      ticks: [[0, "0"], [200, "200%"], [400, "400%"], [600, "600%+"]] },
    { key: "n1y", label: "거래활발도(1년)", min: 0, max: 50, step: 1, u: "건",
      ticks: [[0, "0"], [10, "10건"], [30, "30건"], [50, "50건+"]] },
    { key: "drop", label: "고점대비 하락", min: 0, max: 50, step: 5, u: "%",
      ticks: [[0, "0"], [10, "10%"], [20, "20%"], [30, "30%"], [50, "50%+"]] },
    { key: "sw", label: "역까지 거리", min: 0, max: 1500, step: 100, u: "m",
      ticks: [[0, "0"], [500, "500m"], [1000, "1km"], [1500, "1.5km+"]] },
    { key: "el", label: "초등학교 거리", min: 0, max: 1000, step: 100, u: "m",
      ticks: [[0, "0"], [300, "300m"], [600, "600m"], [1000, "1km+"]] },
  ];
  const F_CFG = Object.fromEntries(F_SLIDERS.map((s) => [s.key, s]));

  // ── 매수 테마 프리셋(주식 스크리너의 '테마'처럼 필터 조합 원클릭 적용) ──
  // range 에 명시한 키만 오버라이드, 나머지는 초기값. lo/hi 는 F_SLIDERS 단위.
  const THEMES = [
    { key: "rebound", icon: "💎", name: "낙폭과대 반등후보",
      desc: "고점대비 -20%↑ 하락 + 1년 거래 5건↑ — 많이 빠졌는데 거래는 살아있는 단지",
      range: { drop: { lo: 20 }, n1y: { lo: 5 } } },
    { key: "mingap", icon: "💰", name: "최소갭 투자",
      desc: "갭 2억↓ + 전세가율 65%↑ — 적은 현금 + 전세 하방쿠션",
      range: { gap: { hi: 2 }, jr: { lo: 65 } } },
    { key: "jdefense", icon: "🛡️", name: "전세방어 실수요",
      desc: "전세가율 60%↑ + 세대수 500↑ + 거래 5건↑ — 하락장에 강한 단지",
      range: { jr: { lo: 60 }, hh: { lo: 500 }, n1y: { lo: 5 } } },
    { key: "station", icon: "🚇", name: "역세권 국평",
      desc: "역 500m↓ + 24~35평 + 세대수 500↑ — 정석 실거주",
      range: { sw: { hi: 500 }, area: { lo: 24, hi: 35 }, hh: { lo: 500 } } },
    { key: "school", icon: "👨‍👩‍👧", name: "초품아 패밀리",
      desc: "초등 400m↓ + 24~41평 + 세대수 700↑ — 가족 수요, 잘 팔림",
      range: { el: { hi: 400 }, area: { lo: 24, hi: 41 }, hh: { lo: 700 } } },
    { key: "newgrand", icon: "🌟", name: "신축 대단지",
      desc: "입주 7년↓ + 세대수 1,000↑ — 신축 프리미엄",
      range: { age: { hi: 7 }, hh: { lo: 1000 } } },
    { key: "redev", icon: "🔨", name: "재건축 잠재",
      desc: "연차 30년↑ + 용적률 200%↓ + 세대수 500↑ — 사업성 있는 후보",
      range: { age: { lo: 30 }, far: { hi: 200 }, hh: { lo: 500 } } },
    { key: "oldgrand", icon: "🏛️", name: "가성비 구축 대단지",
      desc: "연차 20년↑ + 세대수 1,000↑ + 고점대비 -10%↑ — 싸게 사서 오래 보유",
      range: { age: { lo: 20 }, hh: { lo: 1000 }, drop: { lo: 10 } } },
    { key: "momentum", icon: "🚀", name: "신고가 모멘텀",
      desc: "신고가 갱신 + 1년 거래 10건↑ — 시장 주도 단지",
      range: { n1y: { lo: 10 } }, peak: true },
    { key: "liquid", icon: "🔥", name: "환금성 최상",
      desc: "1년 거래 20건↑ + 세대수 1,000↑ — 언제든 팔 수 있는 유동성",
      range: { n1y: { lo: 20 }, hh: { lo: 1000 } } },
  ];

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
    minusGap: false, peak: false, park: false,
    favorites: loadFavorites(), currentDetail: null, chartMode: "sale",
    detailArea: "",   // 상세 패널 면적(평형) 선택 ("" = 전체)
    favDistricts: loadFavDistricts(),   // 관심구(lawd_cd Set)
    subs: [],          // 청약·분양 공고(subscription.json)
    subOverlays: [],   // 청약 마커(실거래 오버레이와 별도 관리)
    listings: null,    // 현재 매물(listings.json) - 최초 패널 열 때 지연 로드
    listingTrade: "sale",   // 매물 섹션 탭: 'sale' | 'jeonse'
    showSubs: localStorage.getItem("seoul_apt_show_subs") !== "0",
    profileOn: false,  // 💼 매수 프로필 적용 상태
    themeKey: null,    // ⭐ 적용 중인 매수 테마 프리셋 키
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
      loadSubs();
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
    $("btn-subs").addEventListener("click", toggleSubsPanel);
    $("subs-close").addEventListener("click", () => toggleSubsPanel(false));
    $("subs-map-toggle").addEventListener("change", (e) => setSubsMarkers(e.target.checked));
    $("btn-dashboard").addEventListener("click", toggleDashboard);
    $("dash-close").addEventListener("click", () => toggleDashboard(false));
    $("btn-buy").addEventListener("click", toggleBuy);
    $("buy-close").addEventListener("click", () => toggleBuy(false));
    $("btn-cost").addEventListener("click", toggleCost);
    $("cost-close").addEventListener("click", () => toggleCost(false));
    $("btn-score").addEventListener("click", () => togglePanel("score"));
    $("score-close").addEventListener("click", () => togglePanel("score", false));
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
      // last_updated 는 export 를 돌린 시각(= 처리시각)이지 실거래 최신 계약일이 아니다.
      // 소스별 실제 기준일은 대시보드 '📅 데이터 기준일' 표(meta.sources)에 있다.
      $("updated-label").textContent =
        "마지막 갱신: " + (state.meta.last_updated_display || "—");
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
    // 가격 푯말을 '매수 후보 찾기' 단지 비교로 드래그해 추가
    el.draggable = true;
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", "cmp:" + mk.id);
      e.dataTransfer.effectAllowed = "copy";
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", () => el.classList.remove("dragging"));
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
    // 현재 선택(포커스)된 단지는 상세 패널과 같은 평형(detailArea)으로 맞춘다.
    // 그래야 "18~26평 저평가"로 매수후보에서 열었을 때 지도 버블도 26평 가격을
    // 보여준다(그냥 헤더 평형필터/대표평형만 쓰면 불일치 - 사고 이력).
    const bucket = (mk.id === state.selectedId && state.detailArea)
      ? state.detailArea
      : state.area || (jeonse ? mk.jrep : mk.rep);
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

  // 갭(매매−전세)은 반드시 '같은 평형'끼리 뺀다. m.sale/m.jeonse 는 전 평형 혼합
  // 중앙값이라 매매 주력이 소형·전세 최근거래가 대형인 단지에서 갭이 뒤집혀
  // '마이너스갭' 오탐이 났다(사고 이력). 전세가율과 같은 원칙으로 맞춘다.
  // 기준 버킷 = 선택 평형, 없으면 매매 대표평형(상세 패널 detailInfo 와 동일).
  function matchedGap(m) {
    const b = state.area || m.rep;
    if (!b) return null;
    const s = m.sale_area && m.sale_area[b];
    const j = m.jeonse_area && m.jeonse_area[b];
    return (s && j) ? s.p - j.p : null;
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
        const g = matchedGap(m);
        if (g == null || g >= 0) return false;
      } else if (active("gap")) {
        const g = matchedGap(m);
        if (!inR("gap", g == null ? null : g / 10000)) return false;
      }
      if (state.peak && !m.is_peak) return false;
      // 지하주차장: 옥내 주차대수>0(대장에 '지하주차장' 항목이 없어 이걸 프록시로).
      // 미수집(null)은 '없음'이 아니라 '모름'이지만, 필터는 확인된 단지만 남긴다.
      if (state.park && !(m.pki > 0)) return false;
      // 고점대비 하락(%): drop은 음수(하락)/0(신고가) → 하락폭 -drop 으로 비교
      if (active("drop") && !inR("drop", m.drop == null ? null : -m.drop)) return false;
      // 입지: 역까지·초등학교까지 거리(m). 상한(역 2km/초등 1.5km) 밖은 null → 제외
      if (active("sw") && !inR("sw", m.sw)) return false;
      if (active("el") && !inR("el", m.el)) return false;
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
    if (state.park) n++;
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
      <div class="range-ticks">${s.ticks.map(([v, t]) => {
        const p = (v - s.min) / (s.max - s.min) * 100;   // 값의 실제 위치
        const tx = p <= 0 ? "0" : p >= 100 ? "-100%" : "-50%";
        return `<span style="left:${p}%;transform:translateX(${tx})">${t}</span>`;
      }).join("")}</div>
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
      if (commit) { clearThemeMark(); onFilterChange(); }
    };
    lo.addEventListener("input", () => upd(false));
    hi.addEventListener("input", () => upd(false));
    lo.addEventListener("change", () => upd(true));
    hi.addEventListener("change", () => upd(true));
    paintRange(s);
  }
  function buildFilterUI() {
    let html = `<div class="theme-box">
      <span class="fs-label">⭐ 매수 테마 <span class="sel-hint">원클릭 필터 조합 · 다시 누르면 해제</span></span>
      <div class="theme-chips">${THEMES.map((t) =>
        `<button class="theme-chip" data-theme="${t.key}" title="${t.desc}">${t.icon} ${t.name}</button>`).join("")}
      </div></div>`;
    html += F_SLIDERS.map(rangeHtml).join("");
    html += `<label class="fs-toggle"><input type="checkbox" id="f-minusgap"> 마이너스 갭 보기 (전세>매매)</label>`;
    html += `<label class="fs-toggle"><input type="checkbox" id="f-peak"> 신고가 단지만</label>`;
    html += `<label class="fs-toggle" title="건축물대장의 옥내 주차대수>0 인 단지만(아파트에서 옥내 주차=사실상 지하주차장). 주차 정보가 아직 수집 안 된 단지는 제외됩니다."><input type="checkbox" id="f-park"> 지하주차장 있는 단지만</label>`;
    $("filter-body").innerHTML = html;
    F_SLIDERS.forEach(bindRange);
    $("f-minusgap").addEventListener("change", (e) => { state.minusGap = e.target.checked; clearThemeMark(); onFilterChange(); });
    $("f-peak").addEventListener("change", (e) => { state.peak = e.target.checked; clearThemeMark(); onFilterChange(); });
    $("f-park").addEventListener("change", (e) => { state.park = e.target.checked; clearThemeMark(); onFilterChange(); });
    document.querySelectorAll(".theme-chip").forEach((b) =>
      b.addEventListener("click", () => applyTheme(b.dataset.theme)));
  }

  // 테마 프리셋 적용/해제. 적용 = 필터 초기화 후 테마 조합만 세팅(누적 아님).
  function applyTheme(key) {
    if (state.themeKey === key) {          // 같은 칩 재클릭 = 해제
      state.themeKey = null;
      resetFilters();
      paintThemeChips();
      toast("테마 해제");
      return;
    }
    const t = THEMES.find((x) => x.key === key);
    if (!t) return;
    F_SLIDERS.forEach((s) => {             // 초기화 + 테마 오버라이드
      const o = (t.range && t.range[s.key]) || {};
      state.range[s.key] = {
        lo: o.lo != null ? o.lo : s.min,
        hi: o.hi != null ? o.hi : s.max,
      };
      const lo = $("rlo-" + s.key), hi = $("rhi-" + s.key);
      if (lo) { lo.value = state.range[s.key].lo; hi.value = state.range[s.key].hi; paintRange(s); }
    });
    state.minusGap = !!t.minusGap;
    state.peak = !!t.peak;
    state.park = !!t.park;
    if ($("f-minusgap")) $("f-minusgap").checked = state.minusGap;
    if ($("f-peak")) $("f-peak").checked = state.peak;
    if ($("f-park")) $("f-park").checked = state.park;
    state.themeKey = key;
    paintThemeChips();
    onFilterChange();
    toast(`${t.icon} ${t.name} 적용`);
  }
  function paintThemeChips() {
    document.querySelectorAll(".theme-chip").forEach((b) =>
      b.classList.toggle("on", b.dataset.theme === state.themeKey));
  }
  // 슬라이더·토글을 수동 조작하면 테마 조합이 깨진 것 → 칩 강조 해제
  function clearThemeMark() {
    if (!state.themeKey) return;
    state.themeKey = null;
    paintThemeChips();
  }

  function resetFilters() {
    F_SLIDERS.forEach((s) => {
      state.range[s.key] = { lo: s.min, hi: s.max };
      const lo = $("rlo-" + s.key), hi = $("rhi-" + s.key);
      if (lo) { lo.value = s.min; hi.value = s.max; }
      paintRange(s);
    });
    state.minusGap = state.peak = state.park = false;
    if ($("f-minusgap")) $("f-minusgap").checked = false;
    if ($("f-peak")) $("f-peak").checked = false;
    if ($("f-park")) $("f-park").checked = false;
    clearThemeMark();
    onFilterChange();
  }
  function onFilterChange() { updateFilterBadge(); applyFilters(); }

  // 필터도 다른 패널과 같은 왼쪽 팝업 슬롯을 쓴다(하나만 열림)
  function toggleFilter(force) { togglePanel("filter", force); }

  function bindFilterUI() {
    buildFilterUI();
    $("btn-filter").addEventListener("click", () => toggleFilter());
    $("filter-close").addEventListener("click", () => toggleFilter(false));
    $("f-close").addEventListener("click", () => toggleFilter(false));
    $("f-reset").addEventListener("click", resetFilters);
    $("f-save-profile").addEventListener("click", saveProfile);
    $("btn-profile").addEventListener("click", toggleProfile);
    updateProfileBtn();
  }

  // ── 나의 매수 프로필: 현재 필터+구+평형+거래유형 스냅샷 저장 → 원클릭 적용 ──
  function loadProfile() {
    try { return JSON.parse(localStorage.getItem("seoul_apt_profile") || "null"); }
    catch { return null; }
  }
  function saveProfile() {
    const p = {
      v: 1, savedAt: new Date().toISOString().slice(0, 10),
      range: state.range, area: state.area,
      districts: [...state.districts], dealType: state.dealType,
      minusGap: state.minusGap, peak: state.peak, park: state.park,
    };
    localStorage.setItem("seoul_apt_profile", JSON.stringify(p));
    state.profileOn = false;   // 저장만. 적용 상태는 [💼] 토글로만 관리
    updateProfileBtn();
    toast("💼 매수 프로필 저장됨 - 헤더 [💼 프로필]로 언제든 적용");
  }
  function applyProfile(p) {
    F_SLIDERS.forEach((s) => {
      const r = (p.range && p.range[s.key]) || { lo: s.min, hi: s.max };
      state.range[s.key] = { lo: r.lo, hi: r.hi };
      const lo = $("rlo-" + s.key), hi = $("rhi-" + s.key);
      if (lo) { lo.value = r.lo; hi.value = r.hi; paintRange(s); }
    });
    state.minusGap = !!p.minusGap; state.peak = !!p.peak; state.park = !!p.park;
    if ($("f-minusgap")) $("f-minusgap").checked = state.minusGap;
    if ($("f-peak")) $("f-peak").checked = state.peak;
    if ($("f-park")) $("f-park").checked = state.park;
    state.area = p.area || "";
    if ($("area-filter")) $("area-filter").value = state.area;
    state.dealType = p.dealType || "sale";
    if ($("deal-type")) $("deal-type").value = state.dealType;
    setSelectedDistricts(new Set(p.districts || []));
    onFilterChange();
  }
  function toggleProfile() {
    const p = loadProfile();
    if (!p) return;
    state.profileOn = !state.profileOn;
    if (state.profileOn) {
      applyProfile(p);
      toast("💼 프로필 적용됨");
    } else {
      resetFilters();
      state.area = ""; if ($("area-filter")) $("area-filter").value = "";
      setSelectedDistricts(new Set());
      toast("프로필 해제");
    }
    updateProfileBtn();
  }
  function updateProfileBtn() {
    const btn = $("btn-profile");
    if (!btn) return;
    const p = loadProfile();
    btn.classList.toggle("hidden", !p);       // 저장된 프로필 있을 때만 노출
    btn.classList.toggle("active", !!state.profileOn);
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

  // 왼쪽 팝업 패널 토글. 대시보드·매수후보·비용계산·청약·필터가 같은 슬롯을
  // 공유해 하나만 열린다(지도 위에 겹쳐 뜨므로 동시에 열면 서로 가린다).
  const LEFT_PANELS = ["dash", "buy", "cost", "subs", "score", "filter"];
  function togglePanel(which, force) {
    const panel = $(which + "-panel");
    const willOpen = typeof force === "boolean" ? force
      : panel.classList.contains("hidden");
    LEFT_PANELS.forEach((p) => {                    // 나머지 닫기
      if (p !== which) $(p + "-panel").classList.add("hidden");
    });
    panel.classList.toggle("hidden", !willOpen);
    const anyOpen = LEFT_PANELS.some((p) => !$(p + "-panel").classList.contains("hidden"));
    document.body.classList.toggle("dash-open", anyOpen);   // 상세패널 비켜주기용
    $("dash-resizer").classList.toggle("hidden", !anyOpen);
    if (willOpen && window.SeoulDash) {
      if (which === "dash") SeoulDash.open();
      else if (which === "buy") SeoulDash.openBuy();
      else if (which === "cost") SeoulDash.openCost();
      else if (which === "subs") SeoulDash.openSubs();
      else if (which === "score") SeoulDash.openScore();
    }
    if (which === "subs" && willOpen && $("subs-map-toggle")) {
      $("subs-map-toggle").checked = state.showSubs;   // 열 때 토글 동기화
    }
  }
  function toggleDashboard(force) { togglePanel("dash", force); }
  function toggleBuy(force) { togglePanel("buy", force); }
  function toggleCost(force) { togglePanel("cost", force); }

  // 왼쪽 팝업 너비를 드래그로 조절(지도 크기는 그대로라 relayout 불필요)
  const DASH_MIN = 320;
  function setDashWidth(px) {
    const max = Math.round(window.innerWidth * 0.8);
    px = Math.max(DASH_MIN, Math.min(Math.round(px), max));
    document.documentElement.style.setProperty("--dash-w", px + "px");
    return px;
  }
  function bindDashResizer() {
    const saved = parseInt(localStorage.getItem("seoul_apt_dash_w"), 10);
    if (saved) setDashWidth(saved);
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
      raf = requestAnimationFrame(() => { raf = 0; setDashWidth(x - 12); });
    });
    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      try { rz.releasePointerCapture(e.pointerId); } catch (_) {}
      document.body.classList.remove("resizing");
      const w = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue("--dash-w"), 10);
      if (w) localStorage.setItem("seoul_apt_dash_w", w);
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

  // 방금 포커스한 좌표가 왼쪽 패널들에 가려지지 않도록 보정.
  // setCenter만 하면 지도 컨테이너의 '진짜 중앙'에 놓이는데, 창 너비 1280px
  // 안팎(왼쪽 팝업+상세 패널이 함께 열린 흔한 폭)에서는 그 자리가 하필 열려
  // 있는 패널 밑이라 마커가 안 보인다(사고 이력). 왼쪽에 붙은 세로 스트립
  // 패널들의 오른쪽 끝까지를 '가려진 폭'으로 보고 남는 쪽으로 밀어서 센터링한다.
  // ⚠ 패널이 지도를 밀어내지 않고 겹쳐 뜨므로(2026-07-23 팝업 전환) 상세 패널
  // 뿐 아니라 열려 있는 왼쪽 팝업(대시보드·필터 등)도 함께 계산해야 한다.
  function centerAvoidingPanel(lat, lon) {
    const map = state.map;
    map.setCenter(new kakao.maps.LatLng(lat, lon));
    const mapEl = $("map");
    if (!mapEl) return;
    const mapRect = mapEl.getBoundingClientRect();
    const overlays = ["panel", ...LEFT_PANELS.map((p) => p + "-panel")]
      .map((id) => $(id))
      .filter((el) => el && !el.classList.contains("hidden"));
    const strips = overlays.map((el) => {
      const r = el.getBoundingClientRect();
      const coversHeight = (Math.min(mapRect.height, r.bottom - mapRect.top)
        - Math.max(0, r.top - mapRect.top)) >= mapRect.height * 0.5;
      return {
        left: Math.max(0, r.left - mapRect.left),
        right: Math.min(mapRect.width, r.right - mapRect.left),
        coversHeight,
      };
      // 모바일 하단시트(가로 전체 폭)나 애매한 겹침은 아래에서 걸러진다
    }).filter((s) => s.coversHeight && s.right > 0 && s.right < mapRect.width)
      .sort((a, b) => a.left - b.left);
    // 왼쪽 가장자리부터 '이어 붙은' 패널들만 가려진 폭으로 친다. 팝업과 상세
    // 패널은 12px 간격으로 나란히 뜨므로 한 덩어리로 이어진다.
    let deadRight = 0;
    strips.forEach((s) => {
      if (s.left <= deadRight + 24) deadRight = Math.max(deadRight, s.right);
    });
    if (deadRight <= 0) return;
    const visibleWidth = mapRect.width - deadRight;
    if (visibleWidth < 80) return;   // 남는 폭이 너무 좁으면 보정 포기
    const desiredX = deadRight + visibleWidth / 2;
    const shiftX = desiredX - mapRect.width / 2;
    if (Math.abs(shiftX) < 1) return;
    try {
      const proj = map.getProjection();
      const centerPt = proj.containerPointFromCoords(map.getCenter());
      const newPt = new kakao.maps.Point(centerPt.x - shiftX, centerPt.y);
      map.setCenter(proj.coordsFromContainerPoint(newPt));
    } catch { /* 프로젝션 실패 시 중앙 센터링 그대로 둠 */ }
  }

  function focusComplex(id, areaHint) {
    const mk = state.markers.find((m) => m.id === id);
    if (!mk || !state.map) return false;
    state.map.setLevel(4);
    state.map.setCenter(new kakao.maps.LatLng(mk.lat, mk.lon));
    state.selectedId = id;
    renderMarkers();
    // openComplex는 비동기(fetch)라 패널이 실제로 열리기(.hidden 해제) 전에는
    // 패널 가림 여부를 판단할 수 없다 - 패널이 열린 뒤에 보정 재센터링한다
    // (먼저 센터링→openComplex 전에 보정하면 항상 hidden 상태로 보여 보정이
    // 스킵되는 버그가 났었다).
    openComplex(mk, areaHint).then(() => centerAvoidingPanel(mk.lat, mk.lon));
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
    focusLatLng: (lat, lon) => {          // 대시보드 청약 행 클릭 → 지도 이동
      if (!state.map || !lat || !lon) return false;
      state.map.setLevel(4);
      centerAvoidingPanel(lat, lon);
      return true;
    },
    getProfile: loadProfile,   // 매수후보 패널의 '내 프로필만' 필터용
    calcCost,   // 비용계산 패널(dashboard.js)이 재사용
    onChange: null,   // dashboard.js 가 등록: (Set) => void
  };

  // ── 청약·분양 마커 ──────────────────────────────────────────────────
  async function loadSubs() {
    try {
      const j = await fetchJSON(DATA + "subscription.json");
      state.subs = j.items || [];
    } catch {
      state.subs = [];
    }
    renderSubMarkers();
    updateSubsBtn();
  }

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // 공고 상태: 예정(D-n) → 접수중 → 발표대기 → 완료
  function subStatus(it) {
    const t = todayStr();
    if (it.rcept_bgn && t < it.rcept_bgn) {
      const days = Math.ceil((new Date(it.rcept_bgn) - new Date(t)) / 86400000);
      return { k: "upcoming", label: days <= 30 ? `D-${days}` : "예정" };
    }
    if (it.rcept_end && t <= it.rcept_end) return { k: "open", label: "접수중" };
    if (it.przwner && t < it.przwner) return { k: "wait", label: "발표대기" };
    return { k: "done", label: "완료" };
  }
  // 공급유형 라벨: 무순위/불법행위 재공급/임의공급 등(secd) 우선, 없으면 kind로 근사.
  function subTypeLabel(it) {
    if (it.secd && it.secd !== "일반공급") return it.secd;
    if (it.kind === "apt") return "일반공급(특별·1·2순위)";
    if (it.kind === "remndr") return "무순위/잔여세대";
    if (it.kind === "optn") return "임의공급";
    return "청약";
  }

  function subVisibleOnMap(it) {
    if (!it.lat || !it.lon) return false;
    const st = subStatus(it);
    if (st.k !== "done") return true;
    // 완료 공고는 접수마감 90일까지만 표시
    if (!it.rcept_end) return false;
    return (new Date(todayStr()) - new Date(it.rcept_end)) / 86400000 <= 90;
  }

  function renderSubMarkers() {
    state.subOverlays.forEach((o) => o.setMap(null));
    state.subOverlays = [];
    if (!state.showSubs || !state.map) return;
    state.subs.filter(subVisibleOnMap).forEach((it) => {
      const st = subStatus(it);
      const el = document.createElement("div");
      el.className = `sub-bubble ${st.k}`;
      // 불법행위재공급·임의공급은 마커에도 유형 표기(무순위·일반과 구분)
      const tShort = it.secd === "불법행위 재공급" ? "불법재공급"
        : it.secd === "임의공급" ? "임의공급"
        : it.kind === "remndr" ? "무순위" : "청약";
      el.innerHTML =
        `<div class="sb-price"><span class="sb-badge">${st.label}</span>${tShort}</div>` +
        `<div class="pb-name">${escapeHtml(it.name)}</div>`;
      el.addEventListener("click", () => showSubDetail(it));
      const ov = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(it.lat, it.lon),
        content: el, yAnchor: 1, clickable: true, zIndex: 5,
      });
      ov.setMap(state.map);
      state.subOverlays.push(ov);
    });
  }

  // 🏷️ 청약 버튼 = 청약 패널 열기(대시보드 등과 슬롯 공유). 지도 마커 표시는
  // 패널 안 토글이 담당(setSubsMarkers).
  function toggleSubsPanel(force) { togglePanel("subs", force); }

  // 지도에 청약 마커 표시 여부(패널 안 토글 체크박스에서 호출)
  function setSubsMarkers(on) {
    state.showSubs = !!on;
    localStorage.setItem("seoul_apt_show_subs", state.showSubs ? "1" : "0");
    renderSubMarkers();
    updateSubsBtn();
  }

  function updateSubsBtn() {
    const btn = $("btn-subs"), cnt = $("subs-count"), tog = $("subs-map-toggle");
    if (tog) tog.checked = state.showSubs;   // 패널 토글 상태 동기화
    if (!btn) return;
    btn.classList.toggle("active", state.showSubs);   // 마커 켜져 있으면 버튼 강조
    const n = state.subs.filter((it) => {
      const k = subStatus(it).k;
      return k === "upcoming" || k === "open";
    }).length;
    cnt.textContent = n;
    cnt.classList.toggle("hidden", !n);
  }

  function showSubDetail(it) {
    const st = subStatus(it);
    const kindTxt = subTypeLabel(it);
    const sched = [
      ["모집공고", it.rcrit], ["청약접수", fmtRange(it.rcept_bgn, it.rcept_end)],
      ["당첨자발표", it.przwner], ["계약", fmtRange(it.cntrct_bgn, it.cntrct_end)],
      ["입주예정", it.mvn ? `${it.mvn.slice(0, 4)}.${it.mvn.slice(4)}` : null],
    ].filter((r) => r[1]);
    let html = `<h2>${escapeHtml(it.name)} <span class="badge sub-badge-${st.k}">${st.label}</span></h2>
      <div class="sub">${kindTxt}${it.gu ? " · " + it.gu : ""}${it.tot ? ` · ${it.tot.toLocaleString()}세대` : ""}${it.cnstrct ? " · " + escapeHtml(it.cnstrct) : ""}</div>
      <div class="sub" style="margin-top:2px">${escapeHtml(it.adres || "")}</div>
      <table class="rank-table" style="margin-top:12px"><tbody>
        ${sched.map(([k, v]) => `<tr><td style="color:var(--muted)">${k}</td><td>${v}</td></tr>`).join("")}
      </tbody></table>`;
    if (it.models && it.models.length) {
      html += `<div class="section-title">주택형별 공급 · 안전마진</div>
        <div class="desc">안전마진 = 반경 1.5km 같은 평형 최근 실거래 대비 분양가 할인율(+면 분양가가 시세보다 쌈)</div>
        <table class="rank-table"><thead><tr>
          <th>주택형</th><th>공급</th><th>일반</th><th>특별</th><th>분양가</th><th>안전마진</th>
        </tr></thead><tbody>` +
        it.models.map((m) => `<tr>
          <td>${escapeHtml(m.ty)}</td><td>${m.ar ? m.ar + "㎡" : "-"}</td>
          <td>${m.hh ?? "-"}</td><td>${m.shh ?? "-"}</td>
          <td>${m.price ? fmt(m.price) : "-"}</td>
          <td>${marginCell(m)}</td></tr>`).join("") +
        `</tbody></table>`;
    }
    if (it.cmpet && it.cmpet.length) {
      html += `<div class="section-title">청약 경쟁률</div>
        <table class="rank-table"><thead><tr>
          <th>주택형</th><th>구분</th><th>접수</th><th>경쟁률</th>
        </tr></thead><tbody>` +
        it.cmpet.map((c) => `<tr>
          <td>${escapeHtml(c.ty)}</td><td>${escapeHtml(c.resd || "-")}</td>
          <td>${c.req != null ? c.req.toLocaleString() : "-"}</td>
          <td>${escapeHtml(c.rate || "-")}</td></tr>`).join("") +
        `</tbody></table>`;
    }
    if (it.url) {
      html += `<div class="btn-row" style="margin-top:12px">
        <a class="chip-btn" href="${escapeHtml(it.url)}" target="_blank" rel="noopener">청약홈 공고 보기 ↗</a></div>`;
    }
    $("modal-content").innerHTML = html;
    $("modal").classList.remove("hidden");
  }

  function fmtRange(a, b) {
    if (!a && !b) return null;
    if (a && b && a !== b) return `${a} ~ ${b}`;
    return a || b;
  }

  // 안전마진 셀: 마진% + 주변시세(표본)
  function marginCell(m) {
    if (m.mgn == null) return '<span class="mgn-na">시세부족</span>';
    const cls = m.mgn > 0 ? "pos" : "neg";
    return `<span class="mgn ${cls}">${m.mgn > 0 ? "+" : ""}${m.mgn}%</span>`
      + `<span class="mgn-sub">주변 ${fmt(m.mkt)}·${m.mkt_n}건</span>`;
  }
  // 공고의 대표 안전마진(주택형 중 최고) - 대시보드/요약용
  function bestMargin(it) {
    const ms = (it.models || []).filter((m) => m.mgn != null);
    if (!ms.length) return null;
    return ms.reduce((a, b) => (b.mgn > a.mgn ? b : a));
  }

  // ── 단지 상세 패널 ──────────────────────────────────────────────────
  // areaHint: 특정 평형 맥락에서 열었을 때(예: 매수후보 리스트의 "18~26평" 저평가
  // 행, 급매 리스트의 실거래 면적) 그 평형으로 상세를 맞추기 위한 힌트.
  // 버킷 키 문자열("60~85㎡") 또는 원시 전용면적(㎡ 숫자) 둘 다 받는다.
  // 힌트 없이 열면(지도에서 직접 클릭 등) 기존처럼 헤더 평형필터→대표평형 순.
  // 힌트를 무시하면 매수후보 리스트에서 "18~26평 저평가"로 열었는데 상세/버블은
  // 단지의 대표평형(다른 평형)을 보여주는 불일치가 난다(사고 이력).
  async function openComplex(mk, areaHint) {
    let detail;
    try {
      detail = await fetchJSON(`${DATA}complex/${mk.lawd_cd}/${mk.id}.json`);
    } catch {
      return;
    }
    state.currentDetail = Object.assign({}, mk, detail);
    const bks = detailBuckets(state.currentDetail);
    const hintBucket = typeof areaHint === "number" ? areaBucket(areaHint) : areaHint;
    state.detailArea = (hintBucket && bks.includes(hintBucket)) ? hintBucket
      : (state.area && bks.includes(state.area)) ? state.area : "";
    await ensureListings();   // 매물 섹션·네이버 링크에 필요(최초 1회만 네트워크)
    renderPanel();
  }

  // 상세 패널: 매매·전세·전세가율을 '같은 평형'으로 맞춘다(선택 평형, 없으면 대표평형).
  // 이래야 전세가율 = 화면의 전세/매매와 일치하고 전세·매매 주력 평형 차이로 왜곡 안 됨.
  function detailInfo(d, jeonse) {
    const byArea = jeonse ? d.jeonse_area : d.sale_area;
    const bucket = state.detailArea || d.rep;   // 전세도 매매 대표평형 기준
    const o = (byArea && bucket) ? byArea[bucket] : null;
    return o ? { price: o.p, py: o.py, stale: !!o.s } : null;
  }
  const cardArea = (info) => (info && info.py ? ` · ${info.py}평` : "");
  // 평단가도 선택 평형 기준으로(d.ppy 는 전 평형 혼합) — 옆 카드들과 기준을 맞춘다
  function panelPpy(d) {
    const v = state.detailArea && (d.valuation_area || {})[state.detailArea];
    return v ? v.cur_ppy : d.ppy;
  }
  const staleTag = (info) =>
    (info && info.stale ? ' <span class="stale-tag">1년+</span>' : "");

  // 밸류에이션 게이지 - 장기 평단가 상 현재 위치 + 전세가율 하방 신호
  function valuationCard(d) {
    // 평형을 고르면 그 평형 밸류에이션(valuation_area)으로 — 전 평형 혼합값과 판정이
    // 갈릴 수 있어(전체 pos 86% vs 135㎡~ 70%) 매수후보 리스트 값과 어긋났다(사고 이력).
    const va = d.valuation_area || {};
    const scoped = state.detailArea && va[state.detailArea];
    const v = scoped || d.valuation;
    if (!v) return "";
    const scopeTag = scoped
      ? `<span class="val-scope">${state.detailArea}</span>`
      : (state.detailArea ? `<span class="val-scope">전체 평형</span>` : "");
    const pos = Math.max(0, Math.min(100, v.pos));
    const jrStrong = v.jr != null && v.jr >= 60;   // 전세가율 60%+ = 하방 쿠션 두꺼움
    let verdict, cls;
    if (pos <= 30 && jrStrong) {
      verdict = "저평가 구간 · 전세가율 높아 하방 견고"; cls = "cheap";
    } else if (pos <= 30) {
      verdict = "5년 범위 하단 · 상대적 저가"; cls = "cheap";
    } else if (pos >= 80) {
      verdict = "5년 범위 상단 · 고점 근접, 추격 주의"; cls = "hot";
    } else {
      verdict = "5년 범위 중단"; cls = "mid";
    }
    const peak = v.vs_peak != null
      ? `역대 고점 대비 <b>${v.vs_peak > 0 ? "+" : ""}${v.vs_peak}%</b>` : "";
    const jr = v.jr != null ? ` · 전세가율 ${v.jr}%` : "";
    return `<div class="valuation ${cls}">
      <div class="val-head">📊 밸류에이션 ${scopeTag}<span class="val-verdict">${verdict}</span></div>
      <div class="vg-track">
        <div class="vg-marker" style="left:${pos}%"><span>${pos}%</span></div></div>
      <div class="vg-labels"><span>5년저점 ${v.lo5.toLocaleString()}</span>
        <span>5년고점 ${v.hi5.toLocaleString()}</span></div>
      <div class="val-sub">현재 <b>${v.cur_ppy.toLocaleString()}</b> 만원/평 · ${peak}${jr} · 표본 ${v.months}개월</div>
    </div>`;
  }

  // ── 실구매 비용 계산기 (2026년 기준 단순 참고) ──────────────────────
  // 취득세: 1주택 6억↓1% / 6~9억 선형(가액억×2/3−3)% / 9억↑3%; 2주택(조정)8%; 3주택+12%
  // areaBucket: 전용면적 버킷 라벨("60~85㎡" 등). 농특세는 전용 85㎡ 초과만 내는데,
  // 마커의 py(평)는 export 시 정수 반올림이라 역환산하면 84.97㎡가 85.95㎡로 부풀어
  // 국민평형이 과세로 오판됐다(사고 이력). 버킷 경계가 정확히 85㎡라 버킷으로 판정한다.
  function calcCost(price, homes, ltvPct, areaBucket) {
    const eok = price / 10000;
    let acqRate;
    if (homes >= 3) acqRate = 12;
    else if (homes === 2) acqRate = 8;
    else acqRate = eok <= 6 ? 1 : eok >= 9 ? 3
      : Math.min(3, Math.max(1, eok * 2 / 3 - 3));
    const acq = price * acqRate / 100;
    const eduRate = homes >= 2 ? 0.4 : acqRate / 10;      // 지방교육세
    const edu = price * eduRate / 100;
    // 농특세: 전용 85㎡ 초과만. 버킷을 모르면(대표평형 없음) 부과하지 않는다.
    const bigArea = areaBucket === "85~135㎡" || areaBucket === "135㎡~";
    const farmRate = !bigArea ? 0 : homes >= 3 ? 1.0 : homes === 2 ? 0.6 : 0.2;
    const farm = price * farmRate / 100;
    // 중개보수 상한요율(매매) + VAT 10%
    let brokRate, brokCap = Infinity;
    if (eok < 0.5) { brokRate = 0.6; brokCap = 25; }
    else if (eok < 2) { brokRate = 0.5; brokCap = 80; }
    else if (eok < 9) brokRate = 0.4;
    else if (eok < 12) brokRate = 0.5;
    else if (eok < 15) brokRate = 0.6;
    else brokRate = 0.7;
    const brok = Math.min(price * brokRate / 100, brokCap) * 1.1;   // VAT 포함
    // 기타: 인지세(10억↓ 15만 / 10억↑ 35만, 1억↓ 7만) + 법무 대략 50만
    const stamp = eok <= 1 ? 7 : eok <= 10 ? 15 : 35;
    const etc = stamp + 50;
    const costs = acq + edu + farm + brok + etc;
    // 규제지역(서울 전역) 주담대 한도 캡(2025-10~): 15억↓ 6억 / 15~25억 4억 /
    // 25억↑ 2억. LTV 를 아무리 높여도 이 상한을 못 넘는다(만원).
    // ⚠ 규제지역 다주택자(2주택 이상)는 주택 구입 목적 주담대 자체가 금지(LTV 0).
    // 이걸 빼면 다주택 열의 '필요 현금'이 수억 과소 표시된다.
    const loanBanned = homes >= 2;
    const loanCap = loanBanned ? 0
      : eok <= 15 ? 60000 : eok <= 25 ? 40000 : 20000;
    const rawLoan = loanBanned ? 0 : price * ltvPct / 100;
    const loan = Math.min(rawLoan, loanCap);
    const loanCapped = rawLoan > loanCap;
    return { acqRate, acq, eduRate, edu, farmRate, farm, brokRate, brok,
             etc, costs, loan, loanCap, loanCapped, loanBanned,
             cash: price - loan + costs };
  }

  // ── 현재 매물(호가) ─────────────────────────────────────────────────
  // listings.json 은 수집한 단지만 들어있는 별도 파일 → 패널 최초 오픈 때 1회 로드.
  async function ensureListings() {
    if (state.listings !== null) return state.listings;
    try {
      const j = await fetchJSON(DATA + "listings.json");
      state.listings = j.complexes || {};
    } catch {
      state.listings = {};   // 미수집/파일없음 → 빈 객체(재시도 안 함)
    }
    return state.listings;
  }

  // 네이버부동산 링크(매핑된 단지번호 있으면 단지 직링크, 없으면 검색)
  function naverUrl(d) {
    const g = state.listings && state.listings[String(d.id)];
    if (g && g.no) return `https://fin.land.naver.com/complexes/${g.no}`;
    const q = encodeURIComponent(`${d.umd || ""} ${d.apt}`.trim());
    return `https://m.land.naver.com/search/result/${q}`;
  }

  function listingsHtml(d) {
    const g = state.listings && state.listings[String(d.id)];
    const link = `<a class="chip-btn nv-link" href="${naverUrl(d)}" target="_blank"
        rel="noopener">네이버부동산 ↗</a>`;
    if (!g) {
      return `<div class="section-title">🏷️ 현재 매물</div>
        <div class="empty">아직 수집되지 않은 단지입니다 ${link}</div>`;
    }
    const trade = state.listingTrade;
    // 선택한 평형대가 있으면 그 버킷 매물만(b 없으면 py→㎡ 폴백)
    const areaSel = state.detailArea;
    const inArea = (r) => !areaSel
      || (r.b ? r.b === areaSel
             : (r.py != null && areaBucket(r.py * M2_PER_PY) === areaSel));
    const rows = (g[trade] || []).filter(inArea);
    const nS = (g.sale || []).filter(inArea).length;
    const nJ = (g.jeonse || []).filter(inArea).length;
    const at = g.at ? g.at.slice(0, 10) : "";
    const areaTag = areaSel ? ` <span class="area-tag">${areaSel}</span>` : "";
    const tabs = `<div class="lst-tabs">
      <button data-lt="sale" class="${trade === "sale" ? "active" : ""}">매매 ${nS}</button>
      <button data-lt="jeonse" class="${trade === "jeonse" ? "active" : ""}">전세 ${nJ}</button>
    </div>`;
    let body;
    if (!rows.length) {
      body = areaSel
        ? '<div class="empty">이 평형에 해당하는 매물 없음</div>'
        : '<div class="empty">해당 유형 매물 없음</div>';
    } else {
      body = `<table class="txns lst-table"><thead><tr>
          <th>호가</th><th>평</th><th>층</th><th>동·향</th>
          ${trade === "sale" ? "<th>실거래대비</th>" : ""}</tr></thead><tbody>
        ${rows.map((r) => `<tr>
          <td><a href="${r.url}" target="_blank" rel="noopener">${fmt(r.p)}${r.mo ? `/${r.mo}` : ""}</a></td>
          <td>${r.py != null ? r.py + "평" : "-"}</td>
          <td>${r.fl != null ? r.fl + (r.ft ? "/" + r.ft : "") : "-"}</td>
          <td>${[r.dong, r.dir].filter(Boolean).join(" ") || "-"}</td>
          ${trade === "sale" ? `<td>${premBadge(r.prem)}</td>` : ""}
        </tr>`).join("")}
      </tbody></table>`;
    }
    return `<div class="section-title">🏷️ 현재 매물${areaTag}
        <span class="lst-at">${at ? at + " 기준" : ""}</span> ${link}</div>
      ${tabs}${body}`;
  }

  // 호가 vs 같은크기(±12%)·최근1년 실거래 중앙값 괴리
  function premBadge(prem) {
    if (prem == null) return '<span class="prem-na" title="같은 크기 최근 실거래 표본 부족">-</span>';
    const cls = prem > 0 ? "up" : prem < 0 ? "down" : "flat";
    const sign = prem > 0 ? "+" : "";
    return `<span class="prem ${cls}" title="같은 크기(±12%) 최근 1년 실거래 중앙값 대비">${sign}${prem}%</span>`;
  }

  function bindListings() {
    document.querySelectorAll(".lst-tabs button").forEach((b) =>
      b.addEventListener("click", () => {
        state.listingTrade = b.dataset.lt;
        renderPanel();
      }));
  }

  // 입지(역세권·초품아) 한 줄 — 도보 약 67m/분 환산
  function locationInfo(d) {
    if (d.subway_m == null && d.school_m == null) return "";
    const walk = (m) => Math.max(1, Math.round(m / 67));
    const parts = [];
    if (d.subway_m != null) {
      const nm = d.subway_nm || "역";
      parts.push(`🚇 ${nm} ${d.subway_m}m<span class="loc-walk">도보 ${walk(d.subway_m)}분</span>`);
    }
    if (d.school_m != null) {
      parts.push(`🏫 초등 ${d.school_m}m<span class="loc-walk">도보 ${walk(d.school_m)}분</span>`);
    }
    return `<div class="loc-info">${parts.join('<span class="loc-sep">·</span>')}</div>`;
  }

  function renderPanel() {
    const d = state.currentDetail;
    const si = detailInfo(d, false), ji = detailInfo(d, true);
    // 전세가율: 전체=백엔드 정밀값(대표 전용면적 ±12%), 특정 평형 선택 시 그 버킷 전세/매매
    const jrPct = state.detailArea
      ? ((si && ji && si.price) ? Math.round(ji.price / si.price * 1000) / 10 : null)
      : d.jeonse_ratio;
    const isFav = state.favorites.some((f) => f.id === d.id);
    const gongsi = latestGongsi(d);
    const el = $("panel-content");
    el.innerHTML = `
      <h2>${d.apt} <button id="fav-star" class="fav-star${isFav ? " on" : ""}"
        title="${isFav ? "관심단지 해제" : "관심단지 등록"}">${isFav ? "★" : "☆"}</button>${d.is_peak ? '<span class="badge peak">신고가</span>' : ""}<span id="p-score"></span></h2>
      <div class="sub">${districtName(d.lawd_cd)}${d.umd ? " " + d.umd : ""} · ${buildYearText(d)}</div>
      ${buildingInfo(d)}
      ${locationInfo(d)}
      ${areaSelectTop(d)}
      <div class="price-cards">
        <div class="card"><div class="label">최근 매매${cardArea(si)}</div>
          <div class="value">${si ? fmt(si.price) : "-"}${staleTag(si)}</div></div>
        <div class="card"><div class="label">평단가(만원/평)${cardArea(si)}</div>
          <div class="value small">${panelPpy(d) ? Math.round(panelPpy(d)).toLocaleString() : "-"}</div></div>
        <div class="card"><div class="label">최근 전세${cardArea(ji)}</div>
          <div class="value small">${ji ? fmt(ji.price) : "-"}${staleTag(ji)}</div></div>
        <div class="card"><div class="label">전세가율${cardArea(si)}</div>
          <div class="value small">${jrPct != null ? jrPct + "%" : "-"}</div></div>
        <div class="card"><div class="label">공시가격 ${gongsi ? "(" + gongsi.year + ")" : ""}</div>
          <div class="value small">${gongsi ? fmt(gongsi.price) : "미매칭"}</div></div>
        <div class="card"><div class="label">공시/실거래</div>
          <div class="value small">${gongsiRatio(d, gongsi)}</div></div>
      </div>

      ${valuationCard(d)}

      ${listingsHtml(d)}

      <div class="section-title">면적별 가격 추세</div>
      <div class="chart-tabs">
        <button data-mode="sale" class="${state.chartMode === "sale" ? "active" : ""}">매매</button>
        <button data-mode="jeonse" class="${state.chartMode === "jeonse" ? "active" : ""}">전세</button>
      </div>
      <div class="chart-wrap"><canvas id="detail-chart"></canvas></div>

      <div class="section-title">최근 매매 실거래${areaLabel()}</div>
      ${recentTxnsTable(d)}

      <div class="section-title">최근 전월세 실거래${areaLabel()}</div>
      ${recentRentsTable(d)}
    `;
    $("panel").classList.remove("hidden");
    // 종합점수 배지(비동기 - 채점은 점수 패널과 같은 캐시라 기준·값이 항상 일치).
    // 순위 산정 제외 단지는 '순위 밖' + 사유. 호버 툴팁에 4축 세부점수 표시.
    if (window.SeoulDash && SeoulDash.scoreBadge) {
      SeoulDash.scoreBadge(d.id).then((b) => {
        const sEl = $("p-score");
        if (!sEl || state.currentDetail !== d) return;   // 다른 단지로 넘어갔으면 폐기
        sEl.innerHTML = b.rank
          ? ` <span class="sc-grade g-${b.grade} p-score-badge" title="종합점수 ${b.preset} · ${b.bucket} 기준
전체 ${b.n.toLocaleString()}개 단지 중 ${b.rank.toLocaleString()}위 (${Math.round(b.total)}점)
${b.axesText}${b.flags ? "\n" + b.flags : ""}">${b.grade} ${Math.round(b.total)} · ${b.rank.toLocaleString()}위</span>`
          : ` <span class="p-score-out" title="종합점수 순위 밖 (${b.preset} · ${b.bucket} 기준)
사유: ${b.reason}">순위 밖</span>`;
      }).catch(() => {});
    }
    $("fav-star").addEventListener("click", () => toggleFavorite(d));
    bindListings();
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
  // 패널 상단 평형 선택기(라벨 포함). 여러 평형인 단지만 표시.
  function areaSelectTop(d) {
    const tabs = areaTabs(d);
    if (!tabs) return "";
    return `<div class="area-select-top">
      <span class="fs-label">평형 선택</span>${tabs}</div>`;
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
  // 세대수·용적률·건폐율·주차 - 헤더(구·준공연차) 바로 아래 컴팩트 한 줄
  function buildingInfo(d) {
    if (!d.households && !d.far && !d.bcr && !d.park_total) return "";
    const item = (label, val, title) =>
      `<span class="binfo-item"${title ? ` title="${title}"` : ""}>${label} <b>${val}</b></span>`;
    let park = "";
    if (d.park_total || d.park_indr != null) {
      const per = (d.park_total && d.households)
        ? (d.park_total / d.households).toFixed(2) : null;
      // 지하주차장 유무는 대장에 항목이 없어 옥내 주차대수>0 을 프록시로 쓴다
      const indr = d.park_indr > 0;
      park = item("주차",
        `${per ? per + "대/세대" : (d.park_total || 0).toLocaleString() + "대"}`
        + `<span class="binfo-park ${indr ? "yes" : "no"}">${indr ? "지하O" : "지상만"}</span>`,
        `총 ${(d.park_total || 0).toLocaleString()}대`
        + ` · 옥내(지하) ${(d.park_indr || 0).toLocaleString()}대`
        + ` · 옥외(지상) ${(d.park_oudr || 0).toLocaleString()}대`
        + `\n건축물대장 기준 · 옥내 주차대수를 지하주차장 유무의 근거로 사용`);
    }
    return `<div class="binfo-row">
      ${item("세대수", d.households ? d.households.toLocaleString() + "세대" : "-")}
      ${item("용적률", d.far ? d.far + "%" : "-")}
      ${item("건폐율", d.bcr ? d.bcr + "%" : "-")}
      ${park}
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
      // 거래일(deal_date)은 KST 날짜라 컷오프도 로컬 기준으로 만든다
      // (toISOString 은 UTC라 00~09시엔 하루 어긋남)
      const cd = new Date(Date.now() - 30 * 86400000);
      const cutoff = `${cd.getFullYear()}-${String(cd.getMonth() + 1).padStart(2, "0")}-${String(cd.getDate()).padStart(2, "0")}`;
      let c = `<table class="rank-table"><thead><tr>
        <th>단지</th><th>자치구</th><th>최근매매</th><th>30일</th><th>직전대비</th><th></th>
        </tr></thead><tbody>`;
      valid.forEach(({ f, d }) => {
        // 30일 변동 요약: 거래수·직전 거래 대비 변동%(같은 크기 ±12% 매칭)·신고가
        const sales = (d.recent_sales || []).filter((r) => !r.canceled);
        const m30 = sales.filter((r) => r.date >= cutoff);
        const last = sales[0];
        let chgTxt = "-";
        if (last && last.area) {
          const prev = sales.slice(1).find((r) =>
            r.area >= last.area * 0.88 && r.area <= last.area * 1.12);
          if (prev) {
            const chg = (last.amount - prev.amount) / prev.amount * 100;
            const cls = chg > 0 ? "chg-up" : chg < 0 ? "chg-down" : "";
            chgTxt = `<span class="${cls}">${chg > 0 ? "+" : ""}${chg.toFixed(1)}%</span>`;
          }
        }
        // 신고가는 백엔드가 같은 크기(±12%) 매칭으로 계산해 마커에 실어둔 is_peak 을 쓴다.
        // (valuation.peak 은 평단가(만원/평)라 거래금액(만원)과 직접 비교하면 항상 참 - 사고 이력)
        const fmk = state.markers.find((m) => m.id === f.id);
        const peakMark = (fmk && fmk.is_peak) ? " 🚩" : "";
        c += `<tr class="fav-c-row" data-id="${f.id}" data-lawd="${f.lawd_cd}">
          <td>${f.apt}${peakMark}</td><td>${districtName(f.lawd_cd)}</td>
          <td>${last ? `${fmt(last.amount)} <span class="sel-hint">${last.date.slice(5)}</span>` : "-"}</td>
          <td>${m30.length}건</td>
          <td>${chgTxt}</td>
          <td class="fav-del" data-kind="c" data-id="${f.id}">✕</td></tr>`;
      });
      c += "</tbody></table>";
      // 텔레그램 단지단위 알림 연동: watchlist.yml complexes 스니펫 복사
      c += `<div class="btn-row" style="margin-top:10px">
        <button id="fav-copy-yml" title="config/watchlist.yml 의 complexes: 에 붙여넣으면 텔레그램 단지 알림이 켜집니다">📋 알림설정 복사</button>
      </div>
      <div class="sel-hint">복사한 내용을 GitHub의 config/watchlist.yml 에 붙여넣으면
        관심단지 거래가 텔레그램 다이제스트 최상단에 표시됩니다</div>`;
      finish(c);
    });
  }

  // ★ 관심단지 목록 → watchlist.yml complexes 스니펫 클립보드 복사
  function copyFavYml() {
    const lines = ["complexes:"];
    state.favorites.forEach((f) => {
      const apt = String(f.apt || "").replace(/"/g, "");
      lines.push(`  - {id: ${f.id}, apt: "${apt}", lawd_cd: "${f.lawd_cd}"}`);
    });
    const text = lines.join("\n");
    (navigator.clipboard ? navigator.clipboard.writeText(text)
      : Promise.reject()).then(
      () => toast("📋 복사됨 - config/watchlist.yml 에 붙여넣기"),
      () => { window.prompt("아래 내용을 복사하세요", text); });
  }

  function bindFavModal() {
    const copyBtn = $("fav-copy-yml");
    if (copyBtn) copyBtn.addEventListener("click", copyFavYml);
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
