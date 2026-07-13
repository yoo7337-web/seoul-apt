/* 구글 로그인 게이트 — localhost는 스킵, 배포 사이트에서만 동작.
   Firebase Auth compat SDK 동적 로드(To-Do career-board 패턴) + 허용 이메일 화이트리스트. */
(() => {
  const LOCAL = ["localhost", "127.0.0.1"].includes(location.hostname);
  if (LOCAL || !window.firebaseConfig) return; // 로컬 개발/미리보기는 게이트 없음

  // --- 게이트 오버레이 (콘텐츠는 로그인 전 숨김) ---
  document.documentElement.style.visibility = "hidden";

  const showGate = (msg) => {
    let ov = document.getElementById("auth-gate");
    if (!ov) {
      ov = document.createElement("div");
      ov.id = "auth-gate";
      ov.style.cssText =
        "position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;align-items:center;" +
        "justify-content:center;gap:18px;background:#f7f8fa;font-family:'Segoe UI','Malgun Gothic',sans-serif;visibility:visible";
      ov.innerHTML =
        `<div style="font-size:2rem">🏙️</div>
         <div style="font-size:1.2rem;font-weight:700;color:#1f2937">서울 아파트 시세 지도</div>
         <div id="auth-msg" style="font-size:.9rem;color:#6b7280"></div>
         <button id="auth-google" style="padding:12px 22px;font-size:1rem;border:1px solid #d1d5db;border-radius:10px;
           background:#fff;cursor:pointer;font-weight:600">🔐 Google 계정으로 로그인</button>`;
      document.documentElement.appendChild(ov);
      document.getElementById("auth-google").addEventListener("click", () => {
        firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider())
          .catch((e) => { document.getElementById("auth-msg").textContent = "로그인 실패: " + e.message; });
      });
    }
    document.getElementById("auth-msg").textContent = msg || "";
    ov.style.display = "flex";
  };

  const hideGate = () => {
    const ov = document.getElementById("auth-gate");
    if (ov) ov.style.display = "none";
    document.documentElement.style.visibility = "visible";
  };

  const loadScript = (src) => new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = src; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });

  (async () => {
    try {
      const V = "10.12.2";
      await loadScript(`https://www.gstatic.com/firebasejs/${V}/firebase-app-compat.js`);
      await loadScript(`https://www.gstatic.com/firebasejs/${V}/firebase-auth-compat.js`);
      firebase.initializeApp(window.firebaseConfig);
      firebase.auth().onAuthStateChanged((user) => {
        if (!user) { showGate("서울 아파트 실거래 지도 — 로그인이 필요합니다"); return; }
        const email = (user.email || "").toLowerCase();
        const ok = (window.ALLOWED_EMAILS || []).some((e) => e.toLowerCase() === email);
        if (!ok) {
          firebase.auth().signOut();
          showGate(`접근 권한이 없는 계정입니다 (${email})`);
          return;
        }
        hideGate();
        // 헤더에 로그아웃 버튼 (1회만)
        if (!document.getElementById("auth-out")) {
          const btn = document.createElement("button");
          btn.id = "auth-out";
          btn.textContent = "로그아웃";
          btn.style.cssText = "float:right;font-size:.75rem;padding:4px 10px;border:1px solid #e5e7eb;" +
            "border-radius:8px;background:#fff;color:#6b7280;cursor:pointer";
          btn.addEventListener("click", () => firebase.auth().signOut());
          document.querySelector("header")?.appendChild(btn);
        }
      });
    } catch (e) {
      // SDK 로드 실패 시에도 잠기지 않도록 안내만 (정적 사이트 특성상 하드락 불가)
      showGate("인증 모듈 로드 실패 — 네트워크 확인 후 새로고침: " + e);
    }
  })();
})();
