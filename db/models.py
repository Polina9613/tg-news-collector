from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def get_period_label(dt: datetime) -> str:
    """datetime → '2026-Q2'"""
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    title: Mapped[str] = mapped_column()
    topics: Mapped[str] = mapped_column()  # JSON: ["банки", "финтех"]
    is_active: Mapped[bool] = mapped_column(default=True)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    raw_posts: Mapped[list["RawPost"]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source id={self.id} username={self.username!r}>"


class RawPost(Base):
    __tablename__ = "raw_posts"
    __table_args__ = (UniqueConstraint("source_id", "message_id", name="uq_source_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    message_id: Mapped[int] = mapped_column()
    channel_username: Mapped[str] = mapped_column()
    post_url: Mapped[str] = mapped_column()
    raw_text: Mapped[str | None] = mapped_column(default=None)
    published_at: Mapped[datetime] = mapped_column()
    collected_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    has_media: Mapped[bool] = mapped_column(default=False)
    is_forwarded: Mapped[bool] = mapped_column(default=False)
    views: Mapped[int | None] = mapped_column(default=None)
    text_hash: Mapped[str | None] = mapped_column(default=None)
    extracted_urls: Mapped[str | None] = mapped_column(default=None)  # JSON: ["https://..."]

    source: Mapped["Source"] = relationship(back_populates="raw_posts")
    news_card: Mapped["NewsCard | None"] = relationship(back_populates="raw_post", uselist=False)

    def __repr__(self) -> str:
        return (
            f"<RawPost id={self.id} message_id={self.message_id}"
            f" channel={self.channel_username!r}>"
        )


class NewsCard(Base):
    __tablename__ = "news_cards"
    __table_args__ = (
        Index("ix_news_cards_relevance_review", "relevance_score", "review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_post_id: Mapped[int] = mapped_column(ForeignKey("raw_posts.id"), unique=True)
    title: Mapped[str | None] = mapped_column(default=None)
    source_title: Mapped[str | None] = mapped_column(default=None)
    post_url: Mapped[str | None] = mapped_column(default=None)
    source_url: Mapped[str | None] = mapped_column(default=None)   # главная внешняя ссылка
    published_at: Mapped[datetime | None] = mapped_column(default=None)
    clean_text: Mapped[str | None] = mapped_column(default=None)
    topics: Mapped[str] = mapped_column(default="[]")    # JSON: ["Финтех", "ИИ"]
    tags: Mapped[str] = mapped_column(default="[]")      # JSON: ["#финтех", "#ии"]
    companies: Mapped[str] = mapped_column(default="[]") # JSON: ["Сбер", "Яндекс"]
    is_ad: Mapped[bool] = mapped_column(default=False)
    relevance_score: Mapped[int] = mapped_column(default=0)
    relevance_label: Mapped[str] = mapped_column(default="irrelevant")
    review_status: Mapped[str] = mapped_column(default="auto")
    publish_status: Mapped[str] = mapped_column(default="draft")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    summary: Mapped[str | None] = mapped_column(default=None)
    llm_relevant: Mapped[bool | None] = mapped_column(default=None)
    llm_enriched: Mapped[bool] = mapped_column(default=False)
    llm_enriched_at: Mapped[datetime | None] = mapped_column(default=None)
    llm_retry_after: Mapped[datetime | None] = mapped_column(default=None)

    raw_post: Mapped["RawPost"] = relationship(back_populates="news_card")
    trend_cases: Mapped[list["TrendCase"]] = relationship(back_populates="news_card")

    def __repr__(self) -> str:
        return (
            f"<NewsCard id={self.id} raw_post_id={self.raw_post_id}"
            f" score={self.relevance_score} status={self.review_status!r}>"
        )


class Trend(Base):
    __tablename__ = "trends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    slug: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    tags: Mapped[str | None]  # JSON-список тегов
    status: Mapped[str] = mapped_column(default="active")  # active / pending / legacy / rejected
    category: Mapped[str | None]  # категория для группировки
    proposed_by_case_id: Mapped[int | None]  # для pending — какой кейс предложил тренд
    first_seen_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    cases: Mapped[list["TrendCase"]] = relationship(back_populates="trend")

    def __repr__(self) -> str:
        return f"<Trend id={self.id} name={self.name!r}>"


class TrendCase(Base):
    __tablename__ = "trend_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    news_card_id: Mapped[int | None] = mapped_column(ForeignKey("news_cards.id"), default=None)
    trend_id: Mapped[int | None] = mapped_column(ForeignKey("trends.id"), default=None)
    trend_name: Mapped[str | None]
    case_title: Mapped[str | None]
    company: Mapped[str | None]
    description: Mapped[str | None]
    how_it_works: Mapped[str | None]
    value: Mapped[str | None]
    source_url: Mapped[str | None]
    market: Mapped[str | None]
    period_label: Mapped[str | None]  # "2026-Q2"
    industry: Mapped[str | None]  # отрасль из фиксированного списка
    is_duplicate: Mapped[bool] = mapped_column(default=False)
    duplicate_of_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("trend_cases.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    news_card: Mapped["NewsCard | None"] = relationship(back_populates="trend_cases")
    trend: Mapped["Trend | None"] = relationship(back_populates="cases")

    def __repr__(self) -> str:
        return f"<TrendCase id={self.id} trend={self.trend_name!r}>"


class BotUser(Base):
    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None]
    first_name: Mapped[str | None]
    last_name: Mapped[str | None]
    role: Mapped[str] = mapped_column(default="analyst")  # admin / analyst
    is_active: Mapped[bool] = mapped_column(default=True)
    joined_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<BotUser id={self.id} tg={self.telegram_id} role={self.role!r}>"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("bot_users.id"))
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[int | None]
    payload: Mapped[str | None]  # JSON
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action!r} target={self.target_type}#{self.target_id}>"


class LLMCallLog(Base):
    """Лог каждого вызова LLM. Используется для анализа расхода токенов."""
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    called_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)

    provider: Mapped[str]
    model: Mapped[str]
    method: Mapped[str]

    news_card_id: Mapped[int | None] = mapped_column(default=None, index=True)
    trend_case_id: Mapped[int | None] = mapped_column(default=None)
    context_note: Mapped[str | None] = mapped_column(default=None)

    prompt_chars: Mapped[int] = mapped_column(default=0)
    response_chars: Mapped[int] = mapped_column(default=0)

    prompt_tokens: Mapped[int | None] = mapped_column(default=None)
    completion_tokens: Mapped[int | None] = mapped_column(default=None)
    total_tokens: Mapped[int | None] = mapped_column(default=None)
    cache_hit_tokens: Mapped[int | None] = mapped_column(default=None)
    cache_miss_tokens: Mapped[int | None] = mapped_column(default=None)

    duration_ms: Mapped[int] = mapped_column(default=0)

    success: Mapped[bool] = mapped_column(default=True)
    error_message: Mapped[str | None] = mapped_column(default=None)

