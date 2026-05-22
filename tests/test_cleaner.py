
from processor.cleaner import clean_text, compute_hash, extract_title


class TestCleanText:
    def test_none_returns_empty(self):
        assert clean_text(None) == ""

    def test_empty_string_returns_empty(self):
        assert clean_text("") == ""

    def test_removes_html_tags(self):
        result = clean_text("<b>Заголовок</b> текст")
        assert "<b>" not in result
        assert "Заголовок" in result

    def test_removes_emojis(self):
        result = clean_text("Текст 🚀 новость")
        assert "🚀" not in result
        assert "Текст" in result

    def test_collapses_multiple_spaces(self):
        result = clean_text("слово    другое")
        assert "  " not in result
        assert "слово другое" in result

    def test_collapses_excessive_newlines(self):
        result = clean_text("строка\n\n\n\n\nдругая строка")
        assert "\n\n\n" not in result

    def test_strips_leading_trailing_whitespace(self):
        result = clean_text("  текст  ")
        assert result == "текст"

    def test_plain_text_unchanged(self):
        text = "Обычный текст без спецсимволов"
        assert clean_text(text) == text

    def test_combined_cleanup(self):
        result = clean_text("<p>Текст 🎉  со всем</p>")
        assert "<p>" not in result
        assert "🎉" not in result
        assert "  " not in result


class TestComputeHash:
    def test_returns_string(self):
        assert isinstance(compute_hash("текст"), str)

    def test_same_input_same_hash(self):
        assert compute_hash("текст") == compute_hash("текст")

    def test_different_inputs_different_hashes(self):
        assert compute_hash("текст1") != compute_hash("текст2")

    def test_hash_length(self):
        assert len(compute_hash("текст")) == 64  # SHA-256 hex


class TestExtractTitle:
    def test_returns_first_nonempty_line(self):
        text = "Первая строка\nВторая строка"
        assert extract_title(text) == "Первая строка"

    def test_skips_empty_first_lines(self):
        text = "\n\nЗаголовок новости\nТекст"
        assert extract_title(text) == "Заголовок новости"

    def test_truncates_at_150(self):
        text = "А" * 200
        assert len(extract_title(text)) == 150

    def test_empty_text_returns_fallback(self):
        assert extract_title("") == "Без заголовка"
