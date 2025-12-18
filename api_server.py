import os
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from main import load_forbidden, generate_candidates, filter_candidates, write_final

app = FastAPI(title="Movie Filter API", version="1.0.0")

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

    cands = generate_candidates(req.style_hint, n=req.n)
    safe = filter_candidates(cands, forbidden)

    if len(safe) < req.k:
        more = generate_candidates(req.style_hint, n=req.n)
        safe += filter_candidates(more, forbidden)

    finals = write_final(safe[:30], k=req.k)

    return {
        "items": [
            {"movie": x.movie, "scene": x.scene, "behind": x.behind, "vibe_point": x.vibe_point}
            for x in finals
        ]
    }
