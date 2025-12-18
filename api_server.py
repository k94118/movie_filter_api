import os
import re
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from main import load_forbidden, generate_candidates, filter_candidates, write_final

app = FastAPI(
    title="Movie Filter API",
    version="1.0.0",
    servers=[{"url": "https://movie-filter-api.onrender.com"}],
)

ACTION_API_KEY = os.getenv("ACTION_API_KEY", "")

def require_auth(authorization: str | None):
    if not ACTION_API_KEY:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token != ACTION_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# -----------------------------
# 1) 금지(별칭 포함) 타이틀 세트
# -----------------------------
def _norm_title(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\W_]+", "", s)
    return s

def _build_forbidden_title_set(forbidden: list[dict]) -> set[str]:
    out: set[str] = set()
    for row in (forbidden or []):
        out.add(_norm_title(row.get("movie", "")))
        for a in (row.get("movie_aliases", []) or []):
            out.add(_norm_title(a))
    out.discard("")
    return out


# -----------------------------
# 2) 응답 크기 제한(Actions 파싱 실패 방지)
# -----------------------------
MAX_STYLE_HINT_CHARS = 800
MAX_SCENE_CHARS = 220
MAX_BEHIND_CHARS = 240
MAX_VIBE_CHARS = 180
MAX_TITLE_CHARS = 120

def _clip(s: str, limit: int) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


class GenerateReq(BaseModel):
    style_hint: str = Field(..., description="원하는 분위기/느낌 요약")

    # ✅ 기본을 10개로(너가 원한 것)
    k: int = Field(10, ge=1, le=10, description="최종 출력 개수 (기본 10)")

    # ✅ n은 최소 10 유지 (커넥터가 n=10 이상 요구해서)
    n: int = Field(30, ge=10, le=80, description="후보 생성 개수 (기본 30, 최소 10)")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate(req: GenerateReq, authorization: str | None = Header(default=None)):
    require_auth(authorization)

    if len(req.style_hint or "") > MAX_STYLE_HINT_CHARS:
        raise HTTPException(status_code=422, detail=f"style_hint too long (max {MAX_STYLE_HINT_CHARS} chars)")

    forbidden = load_forbidden("forbidden.json")
    forbidden_titles = _build_forbidden_title_set(forbidden)

    # -----------------------------
    # 3) 후보를 "부족하면 더 뽑아서" k개 채우기
    # -----------------------------
    # - filter_candidates()가 걸러서 부족해질 수 있으니,
    #   최대 5번까지 후보를 더 뽑아 누적한다.
    safe_pool = []
    tries = 0
    target_k = req.k

    while tries < 5 and len(safe_pool) < max(target_k * 3, 30):
        tries += 1
        cands = generate_candidates(req.style_hint, n=req.n)
        safe_pool += filter_candidates(cands, forbidden)

        # 후보가 너무 많아지면 과도한 토큰/시간 방지
        if len(safe_pool) > 200:
            safe_pool = safe_pool[:200]

    # 후보가 아예 없으면 그대로 반환(빈 리스트)
    if not safe_pool:
        return {"items": []}

    # write_final에 줄 풀(풀은 넉넉히 줘야 10개가 안정적으로 채워짐)
    # k=10이면 30~60개 정도를 재료로 주는 게 안정적
    material = safe_pool[: max(60, target_k * 6)]

    # -----------------------------
    # 4) 최종 작성 → 금지(별칭 포함) 제거 → 중복 제거
    # -----------------------------
    # 부족하면 write_final을 한 번 더 시도 (총 2회)
    cleaned = []

    def _clean(finals):
        out = []
        seen = set()
        for x in finals:
            title = getattr(x, "movie", "")
            key = _norm_title(title)
            if not key:
                continue
            if key in forbidden_titles:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        return out

    finals = write_final(material, k=target_k)
    cleaned = _clean(finals)

    if len(cleaned) < target_k:
        # 재료를 더 넓혀서 한 번 더
        material2 = safe_pool[: max(120, target_k * 10)]
        finals2 = write_final(material2, k=target_k)
        cleaned2 = _clean(finals2)

        # 합쳐서 k개까지 채우기
        seen = set()
        merged = []
        for x in (cleaned + cleaned2):
            key = _norm_title(getattr(x, "movie", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(x)
            if len(merged) >= target_k:
                break
        cleaned = merged

    # -----------------------------
    # 5) ✅ 응답 크기 줄여서 반환(필드 클립)
    # -----------------------------
    items = []
    for x in cleaned[:target_k]:
        items.append({
            "movie": _clip(getattr(x, "movie", ""), MAX_TITLE_CHARS),
            "scene": _clip(getattr(x, "scene", ""), MAX_SCENE_CHARS),
            "behind": _clip(getattr(x, "behind", ""), MAX_BEHIND_CHARS),
            "vibe_point": _clip(getattr(x, "vibe_point", ""), MAX_VIBE_CHARS),
        })

    return {"items": items}
