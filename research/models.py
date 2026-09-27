"""Small immutable values shared by the research pipeline."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BookCandidate:
    """A book discovered in a ranking, before any eligibility filtering."""

    platform: str
    ranking_id: str
    external_book_id: str
    book_url: str
    title: str
    author: str
    category: Optional[str]
    original_rank: int

    def __post_init__(self) -> None:
        for field_name in (
            "platform",
            "ranking_id",
            "external_book_id",
            "book_url",
            "title",
            "author",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.original_rank < 1:
            raise ValueError("original_rank must be a positive integer")
        if self.category is not None and not self.category.strip():
            object.__setattr__(self, "category", None)
