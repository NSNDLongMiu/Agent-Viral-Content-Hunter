import pytest

from hunter.ingest.normalize import canonical_url, detect_language, normalize_title, title_tokens


@pytest.mark.parametrize(("url", "expected"), [
    ("HTTPS://Example.COM:443/Story/?z=2&utm_source=feed&a=3&z=1#section",
     "https://example.com/Story?a=3&z=1&z=2"),
    ("http://example.com:80/?empty=&q=H%C3%A0+N%E1%BB%99i&FBCLID=x",
     "http://example.com/?empty=&q=H%C3%A0+N%E1%BB%99i"),
    ("https://example.com:8443/?gclid=1&igshid=2&si=3&ref=4&ref_src=5&mc_cid=6&mc_eid=7&UTM_Z=8",
     "https://example.com:8443/"),
    ("https://example.com#section", "https://example.com/"),
    ("https://[2606:4700::1111]:443/path/", "https://[2606:4700::1111]/path"),
    ("https://example.com/?q=%FF&p=%FE", "https://example.com/?p=%FE&q=%FF"),
])
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected
    assert canonical_url(expected) == expected


@pytest.mark.parametrize("url", [
    "ftp://example.com/file", "//example.com/file", "https://user:password@example.com/file",
    "http://localhost.", "http://api.localhost", "http://printer.local", "http://127.1",
    "http://192.168.1.2", "http://10.0.0.1", "http://169.254.169.254", "http://[::1]",
    "http://[fd00::1]", "http://[::ffff:10.0.0.1]", "http://224.0.0.1", "http://[::ffff:224.0.0.1]",
])
def test_canonical_url_rejects_invalid_or_non_public_urls(url: str) -> None:
    with pytest.raises(ValueError) as error:
        canonical_url(url)
    assert url not in str(error.value)


def test_title_normalization_keeps_vietnamese_and_han_text() -> None:
    title = "\tＴｈｅ   Hà Nội,\n越南  and  CÔNG-nghệ!"
    assert normalize_title(title) == "The Hà Nội, 越南 and CÔNG-nghệ!"
    assert title_tokens(title) == ["hà", "nội", "越南", "công", "nghệ"]
    assert title_tokens("An update: Straße_2026") == ["update", "strasse", "2026"]


@pytest.mark.parametrize(("text", "language"), [
    ("Tin mới từ Hà Nội", "vi"), ("Đà Nẵng", "vi"), ("气象预报 2026", "zh"),
    ("Open source news 2026!", "en"), ("", "und"), ("2026! 🌧️", "und"),
    ("Привет", "und"), ("résumé", "und"),
])
def test_detect_language(text: str, language: str) -> None:
    assert detect_language(text) == language
