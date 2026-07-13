// Firebase 웹 설정 — To-Do(career-board-fc111) 프로젝트 재사용 (공개 가능한 web config)
// 보안은 Auth 로그인 + 허용 이메일 화이트리스트로 확보. Firestore는 사용하지 않음(Auth 전용).
window.firebaseConfig = {
  apiKey: "AIzaSyDqanuN7rQmx6R1peTzn3SJf_3TkBZpyyw",
  authDomain: "career-board-fc111.firebaseapp.com",
  projectId: "career-board-fc111",
  storageBucket: "career-board-fc111.firebasestorage.app",
  messagingSenderId: "699122227963",
  appId: "1:699122227963:web:80cb1eacf148bef29b6e5e",
};

// 이 계정만 접속 허용 (추가하려면 배열에 이메일 추가)
window.ALLOWED_EMAILS = ["yoo7337@gmail.com"];
