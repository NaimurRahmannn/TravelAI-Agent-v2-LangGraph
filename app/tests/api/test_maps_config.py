import asyncio
from types import SimpleNamespace

import pytest
from fastapi import Response

from app.api.routes.config import maps_config


def _response(*, api_key: str | None):
    settings = SimpleNamespace(
        GEOAPIFY_MAPS_API_KEY=api_key,
        GEMINI_API_KEY="must-not-leak",
        GROQ_API_KEY="must-not-leak",
        GEOAPIFY_API_KEY="must-not-leak",
    )
    response = Response()
    payload = asyncio.run(maps_config(response, settings))
    return response, payload.model_dump(mode="json")


def test_maps_config_returns_only_the_browser_maps_key():
    response, payload = _response(api_key=" browser-key ")

    assert response.headers["cache-control"] == "no-store"
    assert payload == {
        "enabled": True,
        "api_key": "browser-key",
    }


@pytest.mark.parametrize("api_key", [None, " "])
def test_maps_config_disables_missing_or_blank_configuration(api_key):
    response, payload = _response(api_key=api_key)

    assert response.headers["cache-control"] == "no-store"
    assert payload == {
        "enabled": False,
        "api_key": None,
    }


def test_maps_config_route_is_registered_for_get_requests():
    from app.main import app

    assert str(app.url_path_for("maps_config")) == "/config/maps"
