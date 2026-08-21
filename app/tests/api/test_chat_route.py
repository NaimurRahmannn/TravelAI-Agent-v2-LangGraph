import pytest
from starlette.routing import NoMatchFound


def test_chat_route_is_registered_without_streaming_route():
    from app.main import app

    assert str(app.url_path_for("chat")) == "/chat"

    with pytest.raises(NoMatchFound):
        app.url_path_for("chat_stream")


def test_travel_selection_route_is_registered():
    from app.main import app

    assert str(app.url_path_for("select_travel")) == "/trip/select-travel"
