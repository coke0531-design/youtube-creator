# scripts/whiteboard/ — 화이트보드 드로잉 렌더 엔진 (vendored)

**출처**: [geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation) — MIT License (`LICENSE.srt-whiteboard-animation`), commit `696a724` (2026-07-28) 기준. 원 저작자 "江哥是老登啊".
**가져온 것**: `stream_render.py`(연속 필기 엔진) + `render_stream_whiteboard.py`(구역 마스크 편성 + 필기 렌더). 나머지(SRT 분할·프리뷰 HTML·손 이미지·예제·Codex 메타)는 가져오지 않았다 — 우리 파이프라인(transcript 실측·타임라인.json)이 그 역할을 이미 한다.
**개작(2026-08-16, 원본 대비 diff 최소)**:
- stdout/stderr UTF-8 강제(Windows cp949에서 중국어 로그 출력 시 크래시).
- `--canvas` 옵션 노출(배경색; 우리는 `#ffffff` 고정 — 원본 기본값은 미색 `#F6F1E3`).
- 절차적 펜촉(손 자산 없을 때 폴백) 색을 앰버 `#F59E0B`로.
- 원본 손 이미지(`drawing-hand.png`)는 **원 저작자 브랜드 문구가 펜에 인쇄돼 있어 제외**. 우리 손 자산 = `템플릿/whiteboard/hand-marker-amber.svg/.png`(4색 벡터, 자체 제작).

**직접 부르지 않는다** — `scripts/render_whiteboard.py`(래퍼)가 브랜드·파이프라인 계약(흰 배경, 1920x1080·30fps, 정확한 길이, 하단 21% 자막 안전 영역 가드)을 강제하며 호출한다. 사용법은 youtube-editor SKILL.md Step 6.6.

**의존성**: `opencv-python-headless`, `numpy`(requirements.txt에 고정). H.264 트랜스코드는 시스템 ffmpeg → PyAV(`av`) 순으로 폴백(둘 다 없으면 mp4v 유지 — encode_overlays.py가 어차피 재인코딩하므로 결과는 동일).

**업스트림 갱신 시**: 위 개작 3곳만 다시 적용하고 `python scripts/render_whiteboard.py 템플릿/whiteboard/scene-example.svg --out <tmp>/wb1.mp4 --duration 10` 스모크(1920x1080·10.00s)로 확인.

## 롤백 절차 (실측 결과가 별로면 되돌리기)

도입 직전 상태에 태그가 있다: **`pre-whiteboard-2026-08-16`**. 도입은 단일 커밋(`feat(whiteboard): …`)이라 되돌리기는 한 줄이다.

```bash
# 방법 1 — 도입 커밋만 되돌리기(이후 커밋 보존, 권장)
git revert --no-edit <feat(whiteboard) 커밋 해시>     # git log --oneline | grep whiteboard 로 확인
# 방법 2 — 도입 직전으로 완전 복귀(이후 커밋도 날아감 — 다른 작업이 없을 때만)
git reset --hard pre-whiteboard-2026-08-16
# 공통 — 선택 정리
python -m pip uninstall -y opencv-python-headless        # numpy는 다른 도구가 쓸 수 있어 남긴다
```

되돌린 뒤에도 기존 결과물은 안전하다: `style: "whiteboard"`가 없는 타임라인은 이전과 완전히 같은 경로로 처리되고, `style` 키가 남은 타임라인은 옛 코드에서 무시된다(자막이 흰색으로 돌아갈 뿐).
