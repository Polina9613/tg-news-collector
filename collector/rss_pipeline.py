from loguru import logger

from collector.rss import RssCollectResult, collect_rss_source
from config.settings import get_settings


def collect_rss_all(days: float = 7) -> list[RssCollectResult]:
    """Sync RSS sources from YAML to DB then collect all active feeds."""
    from collector.sources_loader import sync_rss_sources_to_db

    settings = get_settings()
    sources = sync_rss_sources_to_db(settings.sources_file)

    if not sources:
        logger.info("[rss] No active RSS sources configured")
        return []

    results = []
    for src in sources:
        result = collect_rss_source(
            source_db_id=src["db_id"],
            source_username=src["username"],
            feed_url=src["feed_url"],
            fetch_full_text=src.get("fetch_full_text", False),
            days=days,
        )
        results.append(result)

    total_saved = sum(r.saved for r in results)
    logger.info(f"[rss] All feeds done — total saved: {total_saved}")
    return results
