import os
import re
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

import copy
from fastapi.responses import JSONResponse

from main import load_forbidden, generate_candidates, filter_candidates, write_final

from response_budget import enforce_response_budget

app = FastAPI(
    title="Movie Filter API",
    version="1.0.0",
    servers=[{"url": "https://movie-filter-api.onrender.com"}],
)

app.openapi_version = "3.0.2"

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

# ✅ Actions 응답 크기 강제 제한(더 강하게)
MAX_STYLE_HINT_CHARS = 500
MAX_TITLE_CHARS = 80
MAX_SCENE_CHARS = 140
MAX_BEHIND_CHARS = 160
MAX_VIBE_CHARS = 120

def _clip(s: str, limit: int) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"

class GenerateReq(BaseModel):
    style_hint: str = Field(..., description="원하는 분위기/느낌 요약")
    k: int = Field(10, ge=1, le=10, description="최종 출력 개수 (기본 10)")
    n: int = Field(10, ge=1, le=80, description="후보 생성 개수 (입력 1~80 허용, 서버에서 최소 10으로 보정)")
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/generate")
def generate(req: GenerateReq, authorization: str | None = Header(default=None)):
    require_auth(authorization)

    if len(req.style_hint or "") > MAX_STYLE_HINT_CHARS:
        raise HTTPException(status_code=422, detail=f"style_hint too long (max {MAX_STYLE_HINT_CHARS} chars)")

    n_eff = max(req.n, 10)

    forbidden = load_forbidden("forbidden.json")
    forbidden_titles = _build_forbidden_title_set(forbidden)

    # 후보를 몇 번 돌려서 k개 채울 재료 확보(최대 4회)
    safe_pool = []
    tries = 0
    while tries < 4 and len(safe_pool) < 120:
        tries += 1
        cands = generate_candidates(req.style_hint, n=n_eff)
        safe_pool += filter_candidates(cands, forbidden)
        if len(safe_pool) > 200:
            safe_pool = safe_pool[:200]

    # 최종 생성
    finals = write_final(safe_pool[:80], k=req.k)

    # 금지(별칭 포함) + 중복 제거
    seen = set()
    cleaned = []
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
        cleaned.append(x)
        if len(cleaned) >= req.k:
            break

    # ✅ 응답을 짧게 잘라서 반환 (ResponseTooLargeError 방지)
    items = []
    for x in cleaned[:req.k]:
        items.append({
            "movie": _clip(getattr(x, "movie", ""), MAX_TITLE_CHARS),
            "scene": _clip(getattr(x, "scene", ""), MAX_SCENE_CHARS),
            "behind": _clip(getattr(x, "behind", ""), MAX_BEHIND_CHARS),
            "vibe_point": _clip(getattr(x, "vibe_point", ""), MAX_VIBE_CHARS),
        })

    resp = {
        "ok": True,
        "k": req.k,
        "n": n_eff,
        "count": len(items),
        "items": items,
    }

    resp = enforce_response_budget(resp)
    return resp


# --- Actions-friendly OpenAPI (forces 3.0.2) ---
def _actions_openapi_spec():
    spec = copy.deepcopy(app.openapi())
    spec["openapi"] = "3.0.2"
    spec["servers"] = [{"url": "https://movie-filter-api.onrender.com"}]
    spec.setdefault("components", {}).setdefault("securitySchemes", {})
    spec["components"]["securitySchemes"]["bearerAuth"] = {"type": "http", "scheme": "bearer"}

    # /generate만 bearerAuth 적용
    try:
        spec["paths"]["/generate"]["post"]["security"] = [{"bearerAuth": []}]
    except Exception:
        pass

    # /health는 공개
    try:
        spec["paths"]["/health"]["get"].pop("security", None)
    except Exception:
        pass

    return spec

@app.get("/actions_openapi.json", include_in_schema=False)
def actions_openapi():
    return JSONResponse(_actions_openapi_spec())
