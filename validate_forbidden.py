import json, re, sys
from pathlib import Path

FORBIDDEN_PATH = Path(__file__).with_name("forbidden.json")
SNAKE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")

def fail(msg: str) -> None:
    print("\n❌ forbidden.json 검사 실패")
    print(msg)
    sys.exit(1)

def main():
    if not FORBIDDEN_PATH.exists():
        fail(f"파일이 없습니다: {FORBIDDEN_PATH}")

    # JSON 파싱 검사(쉼표/괄호 실수도 여기서 잡힘)
    try:
        data = json.loads(FORBIDDEN_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"JSON 문법 오류입니다.\n{e}")

    if not isinstance(data, list):
        fail("최상위는 리스트([ ... ])여야 합니다.")

    required = {"fid", "movie", "scene_keys", "trick_keys"}
    seen_fid = set()
    problems = []
    count = 0

    for i, item in enumerate(data):
        count += 1
        if not isinstance(item, dict):
            problems.append(f"- {i}번째 항목이 객체({{...}})가 아닙니다.")
            continue

        missing = required - set(item.keys())
        if missing:
            problems.append(f"- {i}번째 항목에 키가 빠졌습니다: {sorted(missing)}")

        fid = item.get("fid")
        movie = item.get("movie")
        scene_keys = item.get("scene_keys")
        trick_keys = item.get("trick_keys")

        if not isinstance(fid, str) or not fid.strip():
            problems.append(f"- {i}번째 fid가 문자열이 아닙니다.")
        else:
            if fid in seen_fid:
                problems.append(f"- fid 중복: {fid}")
            seen_fid.add(fid)

        if not isinstance(movie, str) or not movie.strip():
            problems.append(f"- {i}번째 movie가 문자열이 아닙니다.")

        if not isinstance(scene_keys, list) or not all(isinstance(x, str) for x in scene_keys):
            problems.append(f"- {i}번째 scene_keys는 문자열 리스트여야 합니다.")
        if not isinstance(trick_keys, list) or not all(isinstance(x, str) for x in trick_keys):
            problems.append(f"- {i}번째 trick_keys는 문자열 리스트여야 합니다.")

        # 키 형태(선택 규칙): snake_case 권장. 틀려도 치명적은 아니지만 경고로 잡아줌.
        if isinstance(scene_keys, list):
            for x in scene_keys:
                if isinstance(x, str) and x and not SNAKE.match(x):
                    problems.append(f"- {i}번째 scene_keys에 권장형식(snake_case) 아님: {x}")
        if isinstance(trick_keys, list):
            for x in trick_keys:
                if isinstance(x, str) and x and not SNAKE.match(x):
                    problems.append(f"- {i}번째 trick_keys에 권장형식(snake_case) 아님: {x}")

    if problems:
        fail("아래 문제를 고친 뒤 다시 실행하세요:\n" + "\n".join(problems))

    print(f"✅ forbidden.json 검사 통과! (총 {count}개 항목)")
    sys.exit(0)

if __name__ == "__main__":
    main()
