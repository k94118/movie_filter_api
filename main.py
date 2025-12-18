import json
from typing import List
from pydantic import BaseModel
from openai import OpenAI

import copy
from fastapi.responses import JSONResponse

client = OpenAI()

class Candidate(BaseModel):
    movie: str
    scene_keys: List[str]
    trick_keys: List[str]
    one_line_pitch: str

class CandidateBatch(BaseModel):
    candidates: List[Candidate]

class FinalItem(BaseModel):
    movie: str
    scene: str
    behind: str
    vibe_point: str

class FinalBatch(BaseModel):
    items: List[FinalItem]

def load_forbidden(path="forbidden.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_forbidden(c: Candidate, forbidden_list, scene_min=2, trick_min=1) -> bool:
    cmovie = c.movie.strip().lower()
    for f in forbidden_list:
        if cmovie != f["movie"].strip().lower():
            continue
        scene_overlap = len(set(c.scene_keys) & set(f["scene_keys"]))
        trick_overlap = len(set(c.trick_keys) & set(f["trick_keys"]))
        if scene_overlap >= scene_min and trick_overlap >= trick_min:
            return True
    return False

def filter_candidates(cands: List[Candidate], forbidden_list) -> List[Candidate]:
    return [c for c in cands if not is_forbidden(c, forbidden_list)]

def generate_candidates(style_hint: str, n=40) -> List[Candidate]:
    system = (
        "너는 영화 제작 비하인드 기반 소재 발굴가다. "
        "입력된 '느낌'과 비슷한 결의 새로운 영화 장면+제작 트릭 조합 후보를 뽑아라. "
        "후보는 짧은 키로만 제시한다. "
        "scene_keys와 trick_keys는 2~4개 영문 스네이크케이스 키로 작성한다."
    )
    user = f"""
느낌(요약):
{style_hint}

요구:
- 후보 {n}개
- 가능한 한 서로 다른 영화 중심
- 각 후보는 movie, scene_keys, trick_keys, one_line_pitch 포함
"""
    resp = client.responses.parse(
        model="gpt-4o-mini",
        input=[{"role": "system", "content": system},
               {"role": "user", "content": user}],
        text_format=CandidateBatch
    )
    return resp.output_parsed.candidates

def write_final(cands: List[Candidate], k=6) -> List[FinalItem]:
    picked = cands[:k]
    system = (
        "너는 영화 장면/비하인드를 짧고 선명한 한국어로 소개하는 작가다. "
        "주어진 후보를 사람이 읽기 좋게 정리하라. 과장 없이 명확하게."
    )
    payload = {"candidates": [c.model_dump() for c in picked], "count": k}

    resp = client.responses.parse(
        model="gpt-4o-mini",
        input=[{"role": "system", "content": system},
               {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        text_format=FinalBatch
    )
    return resp.output_parsed.items

def main():
    forbidden = load_forbidden("forbidden.json")

    style_hint = (
        "충격적인 장면이 있고, "
        "그 장면이 촬영/특수효과 트릭으로 구현되었다는 반전이 있으며, "
        "현장감과 물리적 장치 느낌이 강한 소재"
    )

    cands = generate_candidates(style_hint, n=40)
    safe = filter_candidates(cands, forbidden)

    if len(safe) < 6:
        more = generate_candidates(style_hint, n=40)
        safe += filter_candidates(more, forbidden)

    safe = safe[:30]
    finals = write_final(safe, k=6)

    for i, x in enumerate(finals, 1):
        print(f"{i}) 영화명: {x.movie}")
        print(f"   - 장면: {x.scene}")
        print(f"   - 비하인드 핵심: {x.behind}")
        print(f"   - 유사한 느낌 포인트: {x.vibe_point}\n")

if __name__ == "__main__":
    main()


# --- Actions-friendly OpenAPI (forces 3.0.2) ---
def _actions_openapi_spec():
    spec = copy.deepcopy(app.openapi())
    spec["openapi"] = "3.0.2"
    spec["servers"] = [{"url": "https://movie-filter-api.onrender.com"}]
    spec.setdefault("components", {}).setdefault("securitySchemes", {})
    spec["components"]["securitySchemes"]["bearerAuth"] = {"type": "http", "scheme": "bearer"}
    try:
        spec["paths"]["/generate"]["post"]["security"] = [{"bearerAuth": []}]
    except Exception:
        pass
    try:
        spec["paths"]["/health"]["get"].pop("security", None)
    except Exception:
        pass
    return spec

@app.get("/actions_openapi.json", include_in_schema=False)
def actions_openapi():
    return JSONResponse(_actions_openapi_spec())
