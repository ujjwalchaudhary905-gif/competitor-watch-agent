from src.tools.fetch_tool import _flag_unrendered_counters, _html_to_text


def test_html_to_text_strips_scripts_and_nav():
    html = """
    <html>
      <head><style>.x{color:red}</style></head>
      <body>
        <nav>Home | About</nav>
        <header>Site Header</header>
        <main>
          <h1>Pricing</h1>
          <p>Plan A: $19.99/mo</p>
          <script>console.log('should not appear')</script>
        </main>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    text = _html_to_text(html)
    assert "Pricing" in text
    assert "$19.99/mo" in text
    assert "should not appear" not in text
    assert "Home | About" not in text
    assert "Copyright 2026" not in text


def test_html_to_text_collapses_blank_lines():
    html = "<p>Line one</p>\n\n\n\n<p>Line two</p>"
    text = _html_to_text(html)
    assert "\n\n\n" not in text


def test_flags_unrendered_js_counter_own_line():
    text = _flag_unrendered_counters("0+\nParcel Records")
    assert "STAT UNAVAILABLE" in text
    assert "Parcel Records" in text
    assert "0+\nParcel" not in text


def test_flags_unrendered_js_counter_same_line():
    text = _flag_unrendered_counters("0+ Counties Covered")
    assert "STAT UNAVAILABLE" in text
    assert "Counties Covered" in text


def test_does_not_flag_legitimate_zero_price():
    text = _flag_unrendered_counters("Price: $0\nFree tier: $0/month")
    assert "STAT UNAVAILABLE" not in text


def test_does_not_flag_real_large_numbers():
    text = _flag_unrendered_counters("150,000+\nreviews")
    assert "STAT UNAVAILABLE" not in text
    assert "150,000+" in text
