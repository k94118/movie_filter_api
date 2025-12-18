import json
from typing import Any, Dict, List

# Actions 제한(요청/응답 각각 100,000 chars 미만) 대비 여유를 둠
MAX_RESPONSE_CHARS = 90_000

FIELD_LIMITS = {
    "movie": 80,
    "title": 80,
    "year": 6,
    "scene": 160,
    "behind": 180,
    "vibe_point": 160,
    "reason": 180,
    "why": 180,
    "notes": 180,
    "aliases": 220,
}

def _clip_text(v: Any, limit: int) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"

def _compact_item(item: Dict[str, Any]) -> Dict[str, Any]:
    keep_keys = ["movie", "title", "year", "scene", "behind", "vibe_point", "reason", "why", "notes", "aliases"]
    out: Dict[str, Any] = {}

    for k in keep_keys:
        if k in item:
            lim = FIELD_LIMITS.get(k, 160)
            out[k] = _clip_text(item.get(k), lim)

    # movie/title 최소 1개는 남기기
    if not out.get("movie") and item.get("movie"):
        out["movie"] = _clip_text(item["movie"], FIELD_LIMITS["movie"])
    if not out.get("movie") and item.get("title"):
        out["movie"] = _clip_text(item["title"], FIELD_LIMITS["movie"])

    # aliases가 리스트면 너무 커지기 쉬움 → 6개만, 각 30자
    if "aliases" in item and isinstance(item["aliases"], list):
        trimmed = [_clip_text(x, 30) for x in item["aliases"][:6]]
        out["aliases"] = ", ".join([t for t in trimmed if t])

    # None/빈값 제거
    return {k: v for k, v in out.items() if v is not None and v != ""}

def _json_len(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

def enforce_response_budget(resp: Dict[str, Any]) -> Dict[str, Any]:
    if "items" in resp and isinstance(resp["items"], list):
        resp["items"] = [
            _compact_item(x if isinstance(x, dict) else {"movie": str(x)})
            for x in resp["items"]
        ]

    if _json_len(resp) <= MAX_RESPONSE_CHARS:
        return resp

    # 2차: 초미니 모드
    mini_keys = ["movie", "year", "vibe_point", "reason"]
    new_items: List[Dict[str, Any]] = []
    for it in resp.get("items", []):
        m = {k: it.get(k) for k in mini_keys if it.get(k)}
        if not m.get("movie") and it.get("title"):
            m["movie"] = it["title"]
        for k in list(m.keys()):
            lim = 120 if k in ("vibe_point", "reason") else 80
            m[k] = _clip_text(m[k], lim)
        new_items.append(m)
    resp["items"] = new_items

    if _json_len(resp) <= MAX_RESPONSE_CHARS:
        return resp

    # 3차: 더 강하게 줄이기 + 잡음 제거
    for it in resp.get("items", []):
        for k, v in list(it.items()):
            it[k] = _clip_text(v, 60 if k != "movie" else 70)

    for noisy in ["debug", "raw", "candidates", "forbidden_hits", "logs"]:
        resp.pop(noisy, None)

    if _json_len(resp) > MAX_RESPONSE_CHARS:
        resp["items"] = [{"movie": _clip_text(it.get("movie", ""), 70)} for it in resp.get("items", [])][:10]
        resp["note"] = "Response compacted to fit Actions payload limits."

    return resp
