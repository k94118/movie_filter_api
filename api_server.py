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


# --- 별칭/정규화(금지 제목) ---
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


# --- 응답 크기 제한(핵심) ---
MAX_STYLE_HINT_CHARS = 800        # 요청도 너무 길면 Actions에서 문제날 수 있어서 방어
MAX_FIELD_CHARS = 300             # movie/scene/behind/vibe_point 각 필드 최대 길이

def _clip(s: str, limit: int = MAX_FIELD_CHARS) -> str:
    s = (s or "")
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


class GenerateReq(BaseModel):
    style_hint: str = Field(..., description="원하는 분위기/느낌 요약")
    k: int = Field(6, ge=1, le=10, description="최종 출력 개수")
    n: int = Field(20, ge=5, le=80, description="후보 생성 개수 (작게 잡으면 응답도 작아짐)")


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

    # 1) 후보 생성 + 기존 필터
    cands = generate_candidates(req.style_hint, n=req.n)
    safe = filter_candidates(cands, forbidden)

    if len(safe) < req.k:
        more = generate_candidates(req.style_hint, n=req.n)
        safe += filter_candidates(more, forbidden)

    # 2) 최종 생성
    finals = write_final(safe[:30], k=req.k)

    # 3) 최종 방어: 금지(별칭 포함) 제거
    cleaned = [x for x in finals if _norm_title(getattr(x, "movie", "")) not in forbidden_titles]

    # 부족하면 1회 보충
    if len(cleaned) < req.k:
        more = generate_candidates(req.style_hint, n=req.n)
        safe2 = filter_candidates(more, forbidden)
        finals2 = write_final((safe + safe2)[:30], k=req.k)
        cleaned2 = [x for x in finals2 if _norm_title(getattr(x, "movie", "")) not in forbidden_titles]

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

    # 4) ✅ 응답 크기 제한: 각 필드를 짧게 잘라서 Actions 파싱 실패 방지
    items = []
    for x in cleaned[:req.k]:
        items.append({
            "movie": _clip(getattr(x, "movie", ""), 120),          # 제목은 더 짧게
            "scene": _clip(getattr(x, "scene", ""), MAX_FIELD_CHARS),
            "behind": _clip(getattr(x, "behind", ""), MAX_FIELD_CHARS),
            "vibe_point": _clip(getattr(x, "vibe_point", ""), 180) # 한 줄 포인트는 더 짧게
        })

    return {"items": items}
