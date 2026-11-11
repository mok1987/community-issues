# 이슈 묶음 (0단계 프로토타입)

여러 커뮤니티 인기글 **제목**을 30분마다 모아서, AI가 같은 사건끼리 묶고 커뮤니티별 분위기를 한 줄로 비교하는 웹페이지.
기획서의 0단계(반응 검증)용이라 서버·DB 없이 GitHub만으로 무료로 돌아간다.

```
수집(run.py) → data/posts.json 누적 → Gemini로 이슈 묶기 → site/issues.json → GitHub Pages
```

## 원칙 (지키면서 확장할 것)
- 제목과 링크만 저장한다. 본문·이미지·댓글은 가져오지 않는다.
- robots.txt가 막는 곳은 자동으로 건너뛴다. User-Agent는 숨기지 않는다.
- 사이트당 30분에 1번 요청한다.
- 일반인 신상 이슈는 제외하고, 확인 안 된 이야기는 '미확인' 표시를 붙인다.
- 삭제 요청이 오면 `issuebundle/sources.py`에서 해당 사이트를 `enabled=False`로 끄면 된다.

## 처음 설정 (10분)
1. **Gemini 무료 키**: https://aistudio.google.com → Get API key. 카드 등록은 필요 없다.
2. **저장소 Secrets**: Settings → Secrets and variables → Actions → New secret → 이름 `GEMINI_API_KEY`.
3. **Pages 켜기**: Settings → Pages → Source를 **GitHub Actions**로 설정.
4. **이름·연락처 바꾸기**: `issuebundle/collect.py`의 `USER_AGENT`에 들어 있는 `YOUR_ID`, `site/index.html`의 `YOUR_EMAIL`.
5. **첫 실행**: Actions 탭 → "이슈 업데이트" → Run workflow. 그다음부터는 30분마다 자동으로 돈다.

## 내 컴퓨터에서 돌리기
```bash
pip install -r requirements.txt
python run.py --check          # 커뮤니티별로 글이 잘 잡히는지 확인 (저장 안 함)
GEMINI_API_KEY=키 python run.py   # 실제 실행
python demo.py                 # 네트워크 없이 예시 데이터로 화면만 확인
cd site && python -m http.server   # http://localhost:8000
python -m pytest -q            # 테스트
```

## 처음에 꼭 확인할 것
- **링크 패턴**: `sources.py`의 `post_pattern`은 각 사이트의 글 주소 모양으로 만든 추정치다. `--check`를 돌려서 "글 링크를 찾지 못함"으로 나오는 사이트는 목록 페이지에서 글 링크 주소를 보고 정규식을 고친다.
- **해외 IP 차단**: GitHub Actions는 미국 서버에서 돈다. 일부 커뮤니티가 해외나 데이터센터 IP를 막으면 그 사이트는 "HTTP 403" 같은 상태로 나온다. 그럴 때는 내 PC에서 작업 스케줄러(cron)로 `run.py`를 돌리고, 결과만 push하도록 바꾼다.
- **무료 한도**: 실행 1번에 Gemini를 1번 호출하므로 하루 48회다. 무료 티어 안에 들어온다.

## 다음 단계 (기획서 1단계)
- 글 조회수·댓글 수를 같이 수집해서 화제성 점수 보강
- Supabase(Postgres + pgvector)로 이전, 임베딩 기반 묶기
- 아침 푸시, 키워드 알림 (PWA)
