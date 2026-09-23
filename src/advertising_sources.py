"""Source-specific configuration for the current Narangd advertising MVP."""

import re

if __package__:
    from .advertising_collection import SourceConfig
else:
    from advertising_collection import SourceConfig


NARANGD_SOURCE = SourceConfig(
    source_type="official_company_page",
    source_name="Dong-A Otsuka Narangd Cider RESCENE sales update",
    source_url=(
        "https://www.donga-otsuka.co.kr/customer/board/"
        "board_content.asp?idx=672&t_name=BOARD13"
    ),
    source_identifier="donga-otsuka:news:672",
    published_at="2026-08-27",
)


def narangd_identity_content(content: str) -> tuple[str, str]:
    stable = re.sub(
        r'(<th\s+class=["\']bdl["\']>\s*조회\s*</th>\s*<td>)\s*\d+\s*(</td>)',
        r"\1{volatile-view-count}\2",
        content,
        flags=re.IGNORECASE,
    )
    return stable, "donga_otsuka_news_without_view_count_v1"
