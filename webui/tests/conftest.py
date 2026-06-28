import pytest

from hannah_webui.app import create_app

from tests.fake_hannah_client import FakeHannahClient


@pytest.fixture
def hannah():
    return FakeHannahClient()


@pytest.fixture
def app(hannah):
    flask_app = create_app(hannah)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    client.post("/login", data={"username": "claude", "password": "claude"})
    return client
