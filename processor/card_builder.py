import json

from sqlalchemy.orm import Session

from db.models import NewsCard, RawPost
from processor.ads import detect_ad
from processor.cleaner import clean_text, compute_hash, extract_title
from processor.relevance import compute_relevance
from processor.tagger import assign_tags, assign_topics, extract_companies


_TRUSTED_DOMAINS = [
    "rbc.ru", "tass.ru", "vedomosti.ru", "cbr.ru",
    "kommersant.ru", "forbes.ru", "habr.com",
    "cnbc.com", "bloomberg.com", "techcrunch.com",
    "interfax.ru", "ria.ru", "banki.ru", "finmarket.ru",
]


def pick_source_url(extracted_urls_json: str | None, post_url: str | None = None) -> str | None:
    """
    Выбирает лучшую ссылку для кейса.
    Приоритет:
    1. Внешняя ссылка с доверенного домена
    2. Первая внешняя ссылка (не t.me)
    3. post_url если внешних нет
    """
    if not extracted_urls_json:
        return post_url
    try:
        urls = json.loads(extracted_urls_json)
    except Exception:
        return post_url

    external = [u for u in urls if "t.me" not in u and u.startswith("http")]
    if not external:
        return post_url

    for url in external:
        if any(domain in url for domain in _TRUSTED_DOMAINS):
            return url

    return external[0]


def build_news_card(raw_post: RawPost, session: Session) -> NewsCard | None:  # noqa: ARG001
    if not raw_post.raw_text:
        return None

    cleaned = clean_text(raw_post.raw_text)
    if cleaned:
        raw_post.text_hash = compute_hash(cleaned)

    raw_text_for_ad = raw_post.raw_text or ""
    is_ad = detect_ad(raw_text_for_ad)
    topics = assign_topics(cleaned)
    tags = assign_tags(cleaned)
    companies = extract_companies(cleaned)
    score, label = compute_relevance(topics, tags, is_ad, cleaned)
    review_status = "needs_review" if (is_ad or score < 10) else "auto"

    source_title: str | None = raw_post.source.title if raw_post.source else None

    return NewsCard(
        raw_post_id=raw_post.id,
        title=extract_title(cleaned) if cleaned else None,
        source_title=source_title,
        post_url=raw_post.post_url,
        source_url=pick_source_url(raw_post.extracted_urls, raw_post.post_url),
        published_at=raw_post.published_at,
        clean_text=cleaned or None,
        topics=json.dumps(topics, ensure_ascii=False),
        tags=json.dumps(tags, ensure_ascii=False),
        companies=json.dumps(companies, ensure_ascii=False),
        is_ad=is_ad,
        relevance_score=score,
        relevance_label=label,
        review_status=review_status,
    )
