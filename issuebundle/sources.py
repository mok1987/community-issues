"""수집 대상 커뮤니티 목록.

원칙 (기획서 '법적 리스크와 안전한 설계 원칙' 참고):
- 공개된 인기글 '목록' 페이지만 읽는다. 로그인 필요한 곳, 본문, 이미지는 가져오지 않는다.
- 각 목록에서 '제목 + 원문 링크'만 저장한다.
- robots.txt가 막는 곳은 자동으로 건너뛴다.

post_pattern 은 목록 페이지 안에서 '게시글 링크'를 골라내는 정규식이다.
사이트 HTML 구조가 바뀌어도 링크 주소 모양은 잘 안 바뀌기 때문에 CSS 선택자 대신 이 방식을 쓴다.
※ 실제 사이트에서 한 번씩 확인이 필요하다: python run.py --check
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str            # 내부 식별자
    name: str           # 화면에 보일 이름
    list_url: str       # 인기글 목록 페이지
    post_pattern: str   # 게시글 링크(href)를 고르는 정규식
    enabled: bool = True
    kind: str = "web"   # "web" = 목록 페이지에서 링크 수집, "youtube" = 공식 API


SOURCES: list[Source] = [
    Source(
        key="dcinside",
        name="디시",
        list_url="https://gall.dcinside.com/board/lists/?id=dcbest",
        post_pattern=r"/board/view/\?id=dcbest&no=\d+",
    ),
    Source(
        key="fmkorea",
        name="에펨코리아",
        list_url="https://www.fmkorea.com/best",
        post_pattern=r"^(https://www\.fmkorea\.com)?/(best/)?\d{7,}$",
    ),
    Source(
        key="theqoo",
        name="더쿠",
        list_url="https://theqoo.net/hot",
        post_pattern=r"^(https://theqoo\.net)?/hot/\d{6,}$",
    ),
    Source(
        key="ruliweb",
        name="루리웹",
        list_url="https://bbs.ruliweb.com/best/humor",
        post_pattern=r"bbs\.ruliweb\.com/best/board/\d+/read/\d+",
    ),
    Source(
        key="natepann",
        name="네이트판",
        list_url="https://pann.nate.com/talk/ranking",
        post_pattern=r"^(https://pann\.nate\.com)?/talk/\d{6,}$",
    ),
    Source(
        key="clien",
        name="클리앙",
        list_url="https://www.clien.net/service/recommend",
        post_pattern=r"^(https://www\.clien\.net)?/service/board/[a-z_]+/\d+",
    ),
    Source(
        key="instiz",
        name="인스티즈",
        list_url="https://www.instiz.net/hot.htm",
        post_pattern=r"instiz\.net/(pt|name|name_enter|free)/\d+|^/(pt|name|name_enter|free)/\d+",
    ),
    Source(
        key="ppomppu",
        name="뽐뿌",
        list_url="https://www.ppomppu.co.kr/hot.php",
        post_pattern=r"view\.php\?id=\w+&no=\d+",
    ),
    Source(
        key="bobaedream",
        name="보배드림",
        list_url="https://www.bobaedream.co.kr/list?code=best",
        post_pattern=r"/view\?code=best&No=\d+",
    ),
    Source(
        key="navernews",
        name="네이버뉴스",
        list_url="https://news.naver.com/main/ranking/popularDay.naver",
        post_pattern=r"n\.news\.naver\.com/(mnews/)?article/\d+/\d+",
    ),
    Source(
        key="daumnews",
        name="다음뉴스",
        list_url="https://news.daum.net/ranking/popular",
        post_pattern=r"v\.daum\.net/v/\d{10,}",
    ),
    # 유튜브는 크롤링이 아니라 공식 API로 가져온다 (issuebundle/youtube.py)
    Source(
        key="youtube",
        name="유튜브",
        list_url="https://www.youtube.com/feed/trending",
        post_pattern=r"youtube\.com/watch\?v=",
        kind="youtube",
    ),
]


def enabled_sources(kind: str | None = None) -> list[Source]:
    return [s for s in SOURCES if s.enabled and (kind is None or s.kind == kind)]
