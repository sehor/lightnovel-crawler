from typing import List, Optional

from pydantic import computed_field
import sqlmodel as sa

from ..context import ctx
from ._base import BaseTable


class Novel(BaseTable, table=True):
    __tablename__ = "novels"  # type: ignore

    domain: str = sa.Field(index=True, description="Domain name of the source website")
    url: str = sa.Field(unique=True, description="Full URL of the novel main page")

    title: str = sa.Field(description="Title of the novel")
    authors: Optional[str] = sa.Field(default=None, description="Comma-separated list of authors")
    synopsis: Optional[str] = sa.Field(
        default=None, description="Brief synopsis or novel description"
    )
    tags: List[str] = sa.Field(
        default=[], sa_type=sa.JSON, description="List of genre or thematic tags"
    )
    ranking_names: List[str] = sa.Field(
        default=[],
        sa_type=sa.JSON,
        sa_column_kwargs={"server_default": "[]"},
        description="Names of rankings the novel appears in",
    )
    source_id: Optional[str] = sa.Field(
        default=None, description="Novel ID assigned by the source website"
    )
    word_count: Optional[int] = sa.Field(
        default=None, sa_type=sa.BigInteger, description="Source-reported novel word count"
    )
    total_recommendations: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Source-reported all-time recommendations",
    )
    weekly_recommendations: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Source-reported weekly recommendations",
    )
    weekly_tipper_count: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Number of readers tipping this week",
    )
    source_chapter_count: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Total serialized chapters reported by the source",
    )
    author_work_count: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Source-reported number of works by the author",
    )
    author_level: Optional[str] = sa.Field(
        default=None, description="Author rank or level reported by the source"
    )
    author_total_word_count: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Source-reported cumulative author word count",
    )
    author_creation_days: Optional[int] = sa.Field(
        default=None,
        sa_type=sa.BigInteger,
        description="Author's reported number of creation days",
    )
    cover_url: Optional[str] = sa.Field(
        default=None,
        description="Cover image URL",
    )

    mtl: bool = sa.Field(default=False, description="True if content is machine-translated")
    rtl: bool = sa.Field(
        default=False, description="True if text reads right-to-left (e.g. Arabic, Hebrew)"
    )
    manga: bool = sa.Field(default=False, description="True if this entry is a manga/manhua/comic")
    language: Optional[str] = sa.Field(
        default=None,
        sa_column=sa.Column(sa.CHAR(2), index=True),
        description="ISO 639-1 two-letter language code (e.g. 'en', 'ja', 'zh')",
    )

    volume_count: int = sa.Field(
        default=0,
        description="Number of available volumes",
    )
    chapter_count: int = sa.Field(
        default=0,
        description="Number of available chapters",
    )

    popularity: int = sa.Field(
        default=0,
        index=True,
        sa_type=sa.BigInteger,
        description="Accumulated all-time reader visits folded in from scrubbed activity",
    )

    @computed_field  # type: ignore[misc]
    @property
    def cover_file(self) -> str:
        """Cover image file path"""
        return f"novels/{self.id}/cover.jpg"

    @computed_field  # type: ignore[misc]
    @property
    def cover_available(self) -> bool:
        """Whether the cover image file is available"""
        return ctx.files.exists(self.cover_file)


class NovelTranslation(BaseTable, table=True):
    __tablename__ = "novel_translations"  # type: ignore
    __table_args__ = (
        sa.UniqueConstraint("novel_id", "language"),
        sa.Index("ix_novel_translation_lookup", "novel_id", "language"),
    )

    novel_id: str = sa.Field(foreign_key="novels.id", ondelete="CASCADE")
    language: str = sa.Field(description="Target language code, e.g. 'fr'")

    title: str = sa.Field(description="Translated title of the novel")
    authors: Optional[str] = sa.Field(default=None, description="Translated list of authors")
    synopsis: Optional[str] = sa.Field(default=None, description="Translated synopsis or novel")


class NovelGlossary(BaseTable, table=True):
    __tablename__ = "novel_glossaries"  # type: ignore
    __table_args__ = (
        sa.UniqueConstraint("novel_id", "language"),
        sa.Index("ix_novel_glossary_lookup", "novel_id", "language"),
    )

    novel_id: str = sa.Field(foreign_key="novels.id", ondelete="CASCADE")
    language: str = sa.Field(description="Target language code, e.g. 'en'")
    terms: dict = sa.Field(
        default={},
        sa_type=sa.JSON,
        description="Source term -> chosen translation, grown across chapters",
    )
