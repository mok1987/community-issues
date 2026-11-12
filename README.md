# 요즘뭐 — 요즘 뭐가 화제야? (0단계 프로토타입)

커뮤니티를 안 보는 바쁜 사람, 나이 든 사람도 "요즘 뭐가 화제인지" 한눈에 알게 해주는 웹페이지.
30분마다 커뮤니티 6곳 인기글 제목과 유튜브 인기 영상을 모으고, AI가 같은 사건끼리 묶어서 쉬운 말로 설명한다.
기획서의 0단계(반응 검증)용이라 서버·DB 없이 GitHub만으로 무료로 돌아간다.

**화면 구성**
- 지금 화제 중: 두 곳 이상에서 동시에 뜬 이슈. 카테고리(정치·경제·사회·문화·연예·스포츠·IT·과학·생활), 왜 화제인지, 쉬운 요약. 누르면 커뮤니티별 분위기(글 제목 기준)와 원래 글 링크. 댓글은 읽지 않고 원래 글에서 직접 보도록 한다.
- 각종 커뮤니티 화제 글 TOP 10 (실시간): 출처별 탭 (수집 불가 출처는 맨 뒤 점선 탭). 쉬운 제목 + 원래 제목, 화제 중 표시. 누르면 원래 글로 이동.
- 글씨 크게 버튼.

```
수집(run.py): 커뮤니티 목록 페이지 + 유튜브 API
  → data/posts.json 누적
  → Gemini ①: 이슈 묶기·카테고리·쉬운 설명·TOP5 쉬운 제목
  → Gemini ②: TOP 10 쉬운 제목
  → site/issues.json → GitHub Pages
```

## 원칙 (지키면서 확장할 것)
- 제목과 링크만 저장한다. 본문·이미지·댓글은 가져오지 않는다.
- robots.txt가 막는 곳은 자동으로 건너뛴다. User-Agent는 숨기지 않는다.
- 사이트당 30분에 1번 요청한다.
- 일반인 신상 이슈는 제외하고, 확인 안 된 이야기는 '미확인' 표시를 붙인다.
- 삭제 요청이 오면 `issuebundle/sources.py`에서 해당 사이트를 `enabled=False`로 끄면 된다.

## 처음 설정 (10분)
1. **Gemini 무료 키**: https://aistudio.google.com → Get API key. 카드 등록은 필요 없다.
2. **유튜브 키 (무료)**: https://console.cloud.google.com → 새 프로젝트 → API 및 서비스 → 라이브러리에서 "YouTube Data API v3" 사용 설정 → 사용자 인증 정보 → API 키 만들기. 하루 무료 할당량 10,000 단위 중 수백 단위만 쓴다.
   - **저장소 Secrets**: Settings → Secrets and variables → Actions → New secret으로 `GEMINI_API_KEY`, `YOUTUBE_API_KEY` 두 개를 등록한다.
3. **Pages 켜기**: Settings → Pages → Source를 **GitHub Actions**로 설정.
4. **연락처**: 삭제 요청 메일은 `site/index.html` 하단, 수집기 이름(User-Agent)은 `issuebundle/collect.py`에 있다.
5. **첫 실행**: Actions 탭 → "이슈 업데이트" → Run workflow. 그다음부터는 30분마다 자동으로 돈다.

## 내 컴퓨터에서 돌리기
```bash
pip install -r requirements.txt
python run.py --check          # 커뮤니티별로 글이 잘 잡히는지 확인 (저장 안 함)
GEMINI_API_KEY=키 YOUTUBE_API_KEY=키 python run.py   # 실제 실행
python demo.py                 # 네트워크 없이 예시 데이터로 화면만 확인
cd site && python -m http.server   # http://localhost:8000
python -m pytest -q            # 테스트
```

## 처음에 꼭 확인할 것
- **링크 패턴**: `sources.py`의 `post_pattern`은 각 사이트의 글 주소 모양으로 만든 추정치다. `--check`를 돌려서 "글 링크를 찾지 못함"으로 나오는 사이트는 목록 페이지에서 글 링크 주소를 보고 정규식을 고친다.
- **해외 IP 차단**: GitHub Actions는 미국 서버에서 돈다. 일부 커뮤니티가 해외나 데이터센터 IP를 막으면 그 사이트는 "HTTP 403" 같은 상태로 나온다. 그럴 때는 내 PC에서 작업 스케줄러(cron)로 `run.py`를 돌리고, 결과만 push하도록 바꾼다.
- **무료 한도**: 실행 1번에 Gemini를 2번 호출하므로 하루 96회다. 무료 티어 안에 들어온다.

## 다음 단계 (기획서 1단계)
- 글 조회수·댓글 수를 같이 수집해서 화제성 점수 보강
- Supabase(Postgres + pgvector)로 이전, 임베딩 기반 묶기
- 아침 푸시, 키워드 알림 (PWA)

## '이게 무슨 말이에요?' 사전 관리
- 화면에는 `data/words.json`(사람이 검수한 사전)에 있는 말만 나온다.
- AI가 제목에서 새로 찾은 말은 `data/word_candidates.json`에 '검토 후보'로 쌓인다. `seen`이 클수록 자주 나온 말.
- 후보의 `ai_meaning`은 AI 초안이라 틀릴 수 있다. 뜻을 확인하고 고쳐서 `words.json`에 옮기면 다음 실행부터 화면에 나온다.
- 욕설이 섞였거나 특정 집단을 비하하는 말은 사전에 넣지 않는다.

## 화제의 인물 TOP 3
- AI가 최근 24시간 제목에서 '공인'만 고르고, 한국어 위키백과에 문서가 있는 사람만 남긴다 (일반인·미성년자·피해자 제외).
- '누구인지'는 위키백과 설명, 사진은 위키미디어 공용(자유 이용)에 있는 것만 쓰고 출처를 표시한다. 없으면 이름 첫 글자로 대신한다.
- 사진이 있어도 상업적 이용 시 초상권·퍼블리시티권 문제가 따로 있을 수 있으니, 정식 서비스 전에 확인할 것.
