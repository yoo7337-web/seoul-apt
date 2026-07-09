"""collect.py 오케스트레이션 - 부분 실패 시 나머지 계속 진행 검증."""

from seoul_apt import collect, config, db
from seoul_apt.molit_api import MolitAPIError


class _FakeClient:
    def __init__(self, fail_on):
        self.fail_on = fail_on   # {(lawd_cd, ymd)} - 여기서 실패 시뮬레이션
        self.calls = []

    def fetch_sales(self, lawd_cd, ymd):
        self.calls.append(("sale", lawd_cd, ymd))
        if (lawd_cd, ymd) in self.fail_on:
            raise MolitAPIError("simulated failure")
        return []

    def fetch_rents(self, lawd_cd, ymd):
        self.calls.append(("rent", lawd_cd, ymd))
        return []


def test_run_backfill_continues_after_one_month_fails(monkeypatch):
    """한 (구,월)의 API 오류가 나머지 구·월 수집을 막으면 안 된다(사고 이력
    회귀 테스트). MolitAPIError 는 RuntimeError 가 아니라서 예전엔 그대로
    전파돼 cli.py 의 except 에도 안 걸리고 배치 전체가 중단됐다."""
    monkeypatch.setattr(config, "SEOUL_DISTRICTS", {"11680": "강남구", "11215": "광진구"})
    fake = _FakeClient(fail_on={("11680", "202602")})
    monkeypatch.setattr(collect, "MolitClient", lambda key: fake)

    conn = db.connect(":memory:")
    stats = collect.run_backfill(conn, "dummy", start_ym="202601", end_ym="202602")

    assert stats["failed"] == ["11680:202602"]
    # 강남 실패 이후에도 광진구는 정상 진행돼야 함(과거엔 여기서 전부 중단됨)
    assert ("sale", "11215", "202601") in fake.calls
    assert ("sale", "11215", "202602") in fake.calls
    # 실패한 (구,월)의 record_fetch 는 기록 안 됨 → 다음 실행 시 자동 재시도
    assert not db.already_fetched(conn, "11680", "202602", "sale")
    # 실패하지 않은 (구,월)은 정상 기록
    assert db.already_fetched(conn, "11680", "202601", "sale")
    conn.close()


def test_run_daily_continues_after_one_month_fails(monkeypatch):
    """일일 수집도 동일하게 부분 실패에서 나머지를 계속 진행해야 한다."""
    monkeypatch.setattr(config, "SEOUL_DISTRICTS", {"11680": "강남구", "11215": "광진구"})
    target_ym = collect._recent_yms(1)[0]   # 실행 시점 기준 최근월(하드코딩 금지)
    fake = _FakeClient(fail_on={("11680", target_ym)})
    monkeypatch.setattr(collect, "MolitClient", lambda key: fake)

    conn = db.connect(":memory:")
    stats = collect.run_daily(conn, "dummy", lookback=1)
    conn.close()

    assert stats["failed"] == [f"11680:{target_ym}"]
    assert ("sale", "11215", target_ym) in fake.calls
