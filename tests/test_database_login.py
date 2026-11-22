"""The database login can come from a secret that changes (Amazon RDS changes a managed password every seven days).

Each new connection asks for the login at that moment, and a password the database refuses is fetched again, once,
before giving up: so a change of password costs one extra round trip, not an outage."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import config, db
from app.db import make_engine


@pytest.fixture()
def real_login():
    url = db.engine.url
    return url.render_as_string(hide_password=False), (url.username, url.password)


def _engine_with(url: str, answers: list) -> tuple:
    """An engine whose login provider gives `answers` in turn, and the list of `refresh` flags it was asked with."""
    asked = []

    def login(refresh: bool):
        asked.append(refresh)
        return answers[len(asked) - 1]
    return make_engine(url, login=login), asked


def test_every_new_connection_logs_in_with_what_the_provider_says_then(real_login):
    url, login = real_login
    stranger = url.replace(f"{login[0]}:{login[1]}@", "nobody:nothing@")     # the URL's own login would be refused
    engine, asked = _engine_with(stranger, [login])

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == login[0]
    assert asked == [False]
    engine.dispose()


def test_a_password_changed_since_it_was_fetched_is_fetched_again_and_the_connection_succeeds(real_login):
    url, login = real_login
    engine, asked = _engine_with(url, [(login[0], "the-password-from-before-the-change"), login])

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
    assert asked == [False, True]                    # refused once, then asked for the newest
    engine.dispose()


def test_a_password_still_refused_after_fetching_again_is_an_error_not_a_loop(real_login):
    url, login = real_login
    engine, asked = _engine_with(url, [(login[0], "wrong"), (login[0], "still-wrong")])

    with pytest.raises(OperationalError, match="password authentication failed"):
        engine.connect()
    assert asked == [False, True]
    engine.dispose()


def test_a_failure_that_is_not_about_the_password_is_not_retried(real_login):
    url, login = real_login
    missing = url.rsplit("/", 1)[0] + "/no_such_database"
    engine, asked = _engine_with(missing, [login, login])

    with pytest.raises(OperationalError):
        engine.connect()
    assert asked == [False]
    engine.dispose()


def test_the_secret_is_fetched_once_and_reused_until_it_is_old_or_a_refresh_is_asked_for(monkeypatch):
    fetched = []

    def fetch(arn):
        fetched.append(arn)
        return {"username": "farm2home", "password": f"password-{len(fetched)}", "engine": "postgres"}
    monkeypatch.setattr(db, "_fetch_secret", fetch)
    monkeypatch.setattr(db, "_secret_login", None)
    monkeypatch.setattr(config, "DB_SECRET_ARN", "arn:aws:secretsmanager:ap-south-1:000000000000:secret:example")

    assert db.secret_login() == ("farm2home", "password-1")
    assert db.secret_login() == ("farm2home", "password-1")                  # from memory
    assert len(fetched) == 1

    assert db.secret_login(refresh=True) == ("farm2home", "password-2")      # the database refused the old one
    assert db.secret_login() == ("farm2home", "password-2")

    monkeypatch.setattr(config, "DB_SECRET_CACHE_SECONDS", 0)                # as if the time had passed
    assert db.secret_login() == ("farm2home", "password-3")
    assert fetched == ["arn:aws:secretsmanager:ap-south-1:000000000000:secret:example"] * 3


def test_without_a_secret_the_app_logs_in_with_the_url_as_before():
    assert config.DB_SECRET_ARN == ""              # the tests set none
    engine = make_engine()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
    engine.dispose()
