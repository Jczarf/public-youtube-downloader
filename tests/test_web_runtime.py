from web.runtime import env_int, max_duration_seconds


def test_env_int_uses_default_for_invalid_value(monkeypatch):
    monkeypatch.setenv("TEST_LIMIT", "invalid")
    assert env_int("TEST_LIMIT", 7, minimum=1, maximum=10) == 7


def test_env_int_clamps_bounds(monkeypatch):
    monkeypatch.setenv("TEST_LIMIT", "999")
    assert env_int("TEST_LIMIT", 7, minimum=1, maximum=10) == 10

    monkeypatch.setenv("TEST_LIMIT", "-4")
    assert env_int("TEST_LIMIT", 7, minimum=1, maximum=10) == 1


def test_zero_can_disable_duration_limit(monkeypatch):
    monkeypatch.setenv("WEB_MAX_DURATION_SECONDS", "0")
    assert max_duration_seconds() == 0


def test_duration_limit_is_capped_to_one_day(monkeypatch):
    monkeypatch.setenv("WEB_MAX_DURATION_SECONDS", "999999")
    assert max_duration_seconds() == 24 * 60 * 60
