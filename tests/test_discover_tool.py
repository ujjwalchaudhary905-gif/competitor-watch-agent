from src.tools.discover_tool import _looks_like_real_page


def test_rejects_error_strings():
    assert not _looks_like_real_page("ERROR: could not fetch https://x.test: timeout")


def test_rejects_short_content():
    assert not _looks_like_real_page("Hi")


def test_rejects_soft_404_pages():
    assert not _looks_like_real_page("404 Not Found\nThe page you requested could not be found." + "x" * 200)


def test_accepts_real_looking_page():
    assert _looks_like_real_page("Pricing\nPlan A: $19.99/mo\nPlan B: $49.99/mo\n" + "Feature details. " * 20)
