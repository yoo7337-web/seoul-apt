import json, urllib.request, urllib.parse
from pathlib import Path

key = ""
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("DATA_GO_KR_KEY="):
        key = line.split("=", 1)[1].strip()
print("key len:", len(key))

def try_api(name, url, extra=None):
    params = dict(extra or {}, serviceKey=key, type="json", numOfRows="3", pageNo="1")
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        print(f"\n=== {name} ===")
        print(body[:700])
    except Exception as e:
        print(f"\n=== {name} FAIL: {e} ===")

try_api("elesch", "https://api.data.go.kr/openapi/tn_pubr_public_elesch_mskul_lc_api")
try_api("subway1", "https://api.data.go.kr/openapi/tn_pubr_public_ubtranes_stn_sttn_api")
try_api("subway2", "https://api.data.go.kr/openapi/tn_pubr_public_city_rlrd_sttn_api")
