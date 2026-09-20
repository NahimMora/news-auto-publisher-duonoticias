from duonoticias_autopublicador.models import news_key, normalize_url, video_key


def test_news_dedupe_priority_and_title_fallback():
    assert news_key({"titulo": "X", "url": "https://source/a", "web_url": "https://hs/a"}) == "source:https://source/a"
    assert news_key({"titulo": "X", "url_wordpress": "https://hs/a"}) == "web:https://hs/a"
    assert news_key({"titulo": "  Una NOTICIA  "}) == "title:una noticia"


def test_video_url_normalization_for_dedupe():
    a = {"source_url": "HTTPS://X.COM:443/User/status/1/?b=2&a=1#fragment"}
    b = {"source_url": "https://x.com/User/status/1?a=1&b=2"}
    assert video_key(a) == video_key(b)
    assert normalize_url(a["source_url"]) == "https://x.com/User/status/1?a=1&b=2"

