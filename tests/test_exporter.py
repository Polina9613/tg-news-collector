import tempfile
from pathlib import Path

from exporter.excel import _bool_to_ru, _json_to_str, export_to_excel


class TestJsonToStr:
    def test_list_joined(self):
        assert _json_to_str('["a", "b", "c"]') == "a, b, c"

    def test_empty_string(self):
        assert _json_to_str("") == ""

    def test_none_returns_empty(self):
        assert _json_to_str(None) == ""

    def test_invalid_json_returns_as_is(self):
        result = _json_to_str("not json")
        assert result == "not json"


class TestBoolToRu:
    def test_true_returns_da(self):
        assert _bool_to_ru(True) == "Да"

    def test_false_returns_empty(self):
        assert _bool_to_ru(False) == ""


class TestExportToExcel:
    def test_creates_file(self, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_export.xlsx")
            result = export_to_excel(output_path=path)
            assert Path(result).exists()

    def test_returns_path_string(self, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_export.xlsx")
            result = export_to_excel(output_path=path)
            assert isinstance(result, str)
