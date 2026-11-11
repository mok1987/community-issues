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
]


def enabled_sources() -> list[Source]:
    return [s for s in SOURCES if s.enabled]
