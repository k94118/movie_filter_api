import os
import re
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from main import load_forbidden, generate_candidates, filter_candidates, write_final

app = FastAPI(
    title="Movie Filter API",
    version="1.0.0",
    # (선택이지만 추천) OpenAPI에 servers를 넣어서 Actions가 URL 못 찾는 문제 방지
    servers=[{"url": "https://movie-filter-api.onrender.com"}],
)

ACTION_API_KEY = os.getenv("ACTION_API_KEY", "")

def require_auth(authorization: str | None):
    if not ACTION_API_KEY:
        return  # 개발 중엔 비워도 됨(배포 시엔 꼭 설정 추천)
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token != ACTION_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# ✅ 별칭까지 확실히 금지하기 위한 유틸
def _norm_title(s: str) -> str:
    s = (s or "").strip().lower()
    # 공백/특수문자/언더스코어 제거 → "타이타닉", "타이타닉(1997)", "Titanic (1997)" 같은 변형을 최대한 동일시
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


class GenerateReq(BaseModel):
    style_hint: str = Field(..., description="원하는 분위기/느낌 요약")
    k: int = Field(6, ge=1, le=10, description="최종 출력 개수")
    n: int = Field(40, ge=10, le=80, description="후보 생성 개수")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate(req: GenerateReq, authorization: str | None = Header(default=None)):
    require_auth(authorization)

    forbidden = load_forbidden("forbidden.json")
    forbidden_titles = _build_forbidden_title_set(forbidden)

    # 1) 후보 생성 + 기존 필터
    cands = generate_candidates(req.style_hint, n=req.n)
    safe = filter_candidates(cands, forbidden)

    if len(safe) < req.k:
        more = generate_candidates(req.style_hint, n=req.n)
        safe += filter_candidates(more, forbidden)

    # 2) 최종 문장화(여기서 다시 금지 영화가 끼어들 수 있으니)
    finals = write_final(safe[:30], k=req.k)

    # ✅ 3) 최종 응답 직전에 "movie + movie_aliases"까지 포함해서 확실히 제거
    cleaned = [x for x in finals if _norm_title(getattr(x, "movie", "")) not in forbidden_titles]

    # k개가 부족하면 1회 보충 시도
    if len(cleaned) < req.k:
        more = generate_candidates(req.style_hint, n=req.n)
        safe2 = filter_candidates(more, forbidden)
        finals2 = write_final((safe + safe2)[:30], k=req.k)

        cleaned2 = [x for x in finals2 if _norm_title(getattr(x, "movie", "")) not in forbidden_titles]

        # 중복 영화 제거하면서 k개까지 채우기
        seen = set()
        merged = []
        for x in (cleaned + cleaned2):
            key = _norm_title(getattr(x, "movie", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(x)
            if len(merged) >= req.k:
                break
        cleaned = merged

    return {
        "items": [
            {"movie": x.movie, "scene": x.scene, "behind": x.behind, "vibe_point": x.vibe_point}
            for x in cleaned[:req.k]
        ]
    }
