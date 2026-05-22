
from processor.ads import detect_ad


class TestDetectAd:
    def test_hashtag_reklama(self):
        assert detect_ad("Купите сейчас #реклама") is True

    def test_word_reklama(self):
        assert detect_ad("реклама в нашем канале") is True

    def test_reklamodatel(self):
        assert detect_ad("Рекламодатель: ООО Ромашка") is True

    def test_erid(self):
        assert detect_ad("erid 2CRrbBTxzFQ") is True

    def test_na_pravah_reklamy(self):
        assert detect_ad("На правах рекламы. Покупайте!") is True

    def test_partnersky_material(self):
        assert detect_ad("Партнёрский материал подготовлен компанией") is True

    def test_case_insensitive(self):
        assert detect_ad("РЕКЛАМА в канале") is True

    def test_regular_news_not_ad(self):
        assert detect_ad("Центральный банк повысил ключевую ставку") is False

    def test_empty_string_not_ad(self):
        assert detect_ad("") is False
