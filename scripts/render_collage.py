"""콜라주 인서트 렌더 — 타임라인.json video_overlays 중 style=="collage" 항목을
cutout-collage-lab(페이퍼 컷아웃 콜라주, Remotion)으로 렌더해 04_영상소스/ov<n>.mp4를 만든다.

왜 이 스크립트인가 (whiteboard 씬의 후속 — 같은 '생성형 오버레이' 패턴):
  실사 오버레이(영상 소스/N.mp4)는 encode_overlays.py가 배속으로 길이를 맞추지만, 콜라주는
  대본(JSON) 자체가 구간 길이와 정확히 일치하게 작성되므로 배속 없이 그대로 렌더한다.
  encode_overlays.py는 style=="collage" 항목을 건너뛴다(재인코딩 시 자기 자신을 덮어씀).

언제 쓰나 — '딱 쓸만한 순간에만' (SSOT: youtube-editor SKILL.md '콜라주 인서트' 절):
  ① 실패담·에피소드 서사(사물이 하나씩 붙으며 이야기가 쌓임) ② 항목 나열·비교(2~3개)
  ③ 수치·비율(종이 파이·막대). 화면 시연·코드 설명·추상 개념 구간은 금지.
  편당 2~3개(오너 확정 2026-08-17 — 전 구간 콜라주 금지), 인서트 합계 ≤ 러닝타임 25%.
  🔒 오프닝 필수(오너 결정 2026-08-18): 영상의 첫 장면(t=0)은 반드시 콜라주 인서트로 연다 —
  시청 시작 시 후킹·몰입. video_overlays에 style=="collage"·start==0.0 항목이 없으면 중단.
  개수 게이트: 오프닝 1 + 본문 1~2 = 2~3개. 4개 이상은 중단, 1개(오프닝만)는 경고.

타임라인 스키마 확장 (video_overlays[] 항목):
  {"n": 2, "src": "04_영상소스/ov2.mp4", "start": 63.2, "end": 106.6,
   "src_dur": 43.4, "label": "…", "style": "collage", "scene": "04_영상소스/collage/cg2.json"}
  - scene: cutout-collage-lab 대본 JSON (스키마 = lab src/schema.ts). 씬 duration 합 = end-start.
  - scene에 caption 필드 금지 — 본편이 자막을 굽는다(흰 상자 자막). 발견 시 중단.
  - src는 이 스크립트가 만드는 ov<n>.mp4 자신을 가리킨다 → validate_pipeline D(원본 존재)·E(길이) 통과.

사용:
  python render_collage.py <작업 폴더 또는 타임라인.json>
  전제: cutout-collage-lab이 LAB 경로에 존재하고 npm ci 되어 있음.
"""
import json
import pathlib
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LAB = pathlib.Path.home() / "Desktop" / "공유 프로젝트" / "cutout-collage-lab"
DUR_TOL = 0.05          # 씬 duration 합 ↔ 오버레이 구간 허용 오차(초)
INSERT_MAX_RATIO = 0.25  # 콜라주 인서트 합계 ≤ 러닝타임 25% (가드)
OPENING_TOL = 0.001      # 오프닝 인서트 start == 0 판정 허용 오차(초)
COUNT_MAX = 3            # 편당 콜라주 인서트 상한 (오프닝 1 + 본문 ≤2)
COUNT_MIN = 2            # 권장 하한 (미만이면 경고 — 오프닝만 있는 편)


def _scene_total(scene: dict) -> float:
    return sum(float(sc["duration"]) for sc in scene["scenes"])


def _check_scene(scene_path: pathlib.Path, seg: float) -> dict:
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    total = _scene_total(scene)
    if abs(total - seg) > DUR_TOL:
        sys.exit(f"[중단] {scene_path.name}: 씬 duration 합 {total:.2f}s ≠ 구간 {seg:.2f}s (±{DUR_TOL}s) — "
                 f"콜라주 대본 시간을 오버레이 구간에 정확히 맞추세요")
    for sc in scene["scenes"]:
        if sc.get("caption"):
            sys.exit(f"[중단] {scene_path.name} 씬 '{sc['id']}'에 caption 있음 — "
                     f"본편이 흰 상자 자막을 굽으므로 콜라주 대본에서 caption을 제거하세요")
    # 겹침·자막 띠·화면 밖 검사 (lab 검사기, fail-loud)
    chk = subprocess.run([sys.executable, str(LAB / "tools" / "check_layout.py"),
                          str(scene_path), "--strict"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if chk.returncode != 0:
        print(chk.stdout, file=sys.stderr)
        sys.exit(f"[중단] {scene_path.name}: 겹침 검사 실패 — 위 경고를 해소하세요 (tools/check_layout.py)")
    return scene


def _render(scene_path: pathlib.Path, out: pathlib.Path):
    job = LAB / "public" / "job"
    job.mkdir(parents=True, exist_ok=True)
    shutil.copy2(scene_path, job / "scene.json")
    npm = shutil.which("npm") or "npm"
    # npx 직접 호출은 보안 훅이 차단 — npm 스크립트 경유 (render_final.py와 동일)
    proc = subprocess.run([npm, "run", "render:job"], cwd=str(LAB))
    if proc.returncode != 0:
        sys.exit(f"[실패] 콜라주 렌더 실패 (npm run render:job exit {proc.returncode})")
    rendered = LAB / "out" / "job.mp4"
    if not rendered.is_file():
        sys.exit(f"[실패] 렌더 산출물 없음: {rendered}")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered, out)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("사용: python render_collage.py <작업 폴더 또는 타임라인.json>")
    arg = pathlib.Path(sys.argv[1]).resolve()
    timeline = arg if arg.is_file() else arg / "타임라인.json"
    if not timeline.is_file():
        sys.exit(f"[오류] 타임라인.json 없음: {timeline}")
    if not (LAB / "package.json").is_file():
        sys.exit(f"[오류] cutout-collage-lab 없음: {LAB}")
    base = timeline.parent

    tl = json.loads(timeline.read_text(encoding="utf-8"))
    targets = [o for o in (tl.get("video_overlays") or []) if o.get("style") == "collage"]
    if not targets:
        sys.exit("[중단] style=='collage'인 video_overlays 항목이 없습니다.")

    if tl.get("type", "main") == "main":
        # 🔒 오프닝 게이트 — 첫 장면(t=0)은 반드시 콜라주 (SKILL.md Step 6.7, 2026-08-18)
        if not any(abs(float(o["start"])) <= OPENING_TOL for o in targets):
            firsts = ", ".join(f"ov{o['n']}@{float(o['start']):.2f}s" for o in sorted(targets, key=lambda o: o["start"]))
            sys.exit("[중단] 콜라주 오프닝 인서트 없음 — 영상의 첫 장면(t=0)은 반드시 콜라주로 시작해야 합니다 "
                     f"(현재 콜라주: {firsts}). video_overlays에 start=0.0 · style=\"collage\" 항목을 추가하세요 "
                     "(SKILL.md Step 6.7 '오프닝 콜라주 필수')")
    if len(targets) > COUNT_MAX:
        sys.exit(f"[중단] 콜라주 인서트 {len(targets)}개 > 상한 {COUNT_MAX} — 오프닝 1 + 본문 1~2개만 (SKILL.md Step 6.7)")
    if len(targets) < COUNT_MIN:
        print(f"[경고] 콜라주 인서트 {len(targets)}개 — 권장은 오프닝 1 + 본문 1~2 = 2~3개입니다 (본문 대목이 없으면 그대로 진행)")

    duration = float(tl.get("duration") or 0)
    insert_sum = sum(float(o["end"]) - float(o["start"]) for o in targets)
    if duration and insert_sum > duration * INSERT_MAX_RATIO:
        sys.exit(f"[중단] 콜라주 인서트 합계 {insert_sum:.1f}s > 러닝타임의 {INSERT_MAX_RATIO:.0%} "
                 f"({duration * INSERT_MAX_RATIO:.1f}s) — '딱 쓸만한 순간에만' 원칙 위반 (SKILL.md 콜라주 절)")

    for o in targets:
        n = o["n"]
        seg = float(o["end"]) - float(o["start"])
        scene_rel = o.get("scene")
        if not scene_rel:
            sys.exit(f"[오류] 오버레이 {n}: style=='collage'인데 scene 필드가 없습니다")
        scene_path = (base / scene_rel).resolve()
        if not scene_path.is_file():
            sys.exit(f"[오류] 오버레이 {n}: 콜라주 대본 없음: {scene_path}")
        _check_scene(scene_path, seg)
        out = base / "04_영상소스" / f"ov{n}.mp4"
        print(f"[렌더] ov{n} ← {scene_rel} (구간 {seg:.2f}s) — Remotion 렌더, 수 분 걸릴 수 있습니다...")
        _render(scene_path, out)
        o["src"] = f"04_영상소스/ov{n}.mp4"
        o["src_dur"] = round(seg, 3)
        print(f"  ov{n}: 완료 → {out}")

    tmp = timeline.with_suffix(".json.tmp")   # src/src_dur 반영 (원자적 쓰기, encode_overlays와 동일)
    tmp.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(timeline)
    print(f"[완료] 콜라주 인서트 {len(targets)}개 (합계 {insert_sum:.1f}s"
          + (f", 러닝타임의 {insert_sum / duration:.0%}" if duration else "") + ")")


if __name__ == "__main__":
    main()
