
from processor.dedup import compute_hash, is_duplicate


class TestIsDeuplicate:
    def test_not_duplicate_when_absent(self, db_session, sample_source):
        result = is_duplicate(db_session, sample_source.id, 9999)
        assert result is False

    def test_is_duplicate_when_present(self, db_session, sample_source, sample_raw_post):
        result = is_duplicate(db_session, sample_source.id, sample_raw_post.message_id)
        assert result is True

    def test_different_source_not_duplicate(self, db_session, sample_source, sample_raw_post):
        result = is_duplicate(db_session, sample_source.id + 999, sample_raw_post.message_id)
        assert result is False


class TestComputeHashReexport:
    def test_compute_hash_available(self):
        h = compute_hash("тест")
        assert len(h) == 64
