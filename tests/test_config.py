from src.config import Competitor, load_business_profile, load_competitors


def test_load_business_profile():
    profile = load_business_profile()
    assert profile.name
    assert profile.site
    assert profile.description


def test_load_competitors():
    competitors = load_competitors()
    assert len(competitors) >= 1
    for c in competitors:
        assert isinstance(c, Competitor)
        assert c.urls
