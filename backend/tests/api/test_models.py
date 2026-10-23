from __future__ import annotations

from app.api import models as models_api
from tests.conftest import ORIGIN, AppHarness


def test_models_require_authentication(harness: AppHarness) -> None:
    response = harness.client.get("/demo/api/models")
    assert response.status_code == 401


def test_models_list_the_local_default_and_unconfigured_backup(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303

    response = harness.client.get("/demo/api/models")
    assert response.status_code == 200
    body = response.json()
    assert body["default"] == "local"
    by_id = {item["id"]: item for item in body["models"]}
    assert by_id["local"]["available"] is True
    assert by_id["local"]["model"] == "gemma-4-26b-a4b-awq"
    assert by_id["deepseek"]["available"] is False
    assert by_id["deepseek"]["hint"] is None


def test_saving_a_deepseek_key_never_returns_the_raw_key(
    harness: AppHarness, login, monkeypatch
) -> None:
    async def verified(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(models_api, "_verify_deepseek", verified)
    assert login(harness.client).status_code == 303
    secret = "sk-test-secret-abcdefghijklmnop"

    response = harness.client.put(
        "/demo/api/models/deepseek-key",
        json={"api_key": secret},
        headers=ORIGIN,
    )
    assert response.status_code == 200
    assert secret not in response.text
    body = response.json()
    assert body["verified"] is True
    by_id = {item["id"]: item for item in body["models"]}
    assert by_id["deepseek"]["available"] is True
    assert by_id["deepseek"]["hint"] == "••••mnop"

    cleared = harness.client.delete(
        "/demo/api/models/deepseek-key",
        headers=ORIGIN,
    )
    assert cleared.status_code == 200
    by_id = {item["id"]: item for item in cleared.json()["models"]}
    assert by_id["deepseek"]["available"] is False
    assert by_id["deepseek"]["hint"] is None


def test_empty_deepseek_key_is_rejected(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = harness.client.put(
        "/demo/api/models/deepseek-key",
        json={"api_key": "   "},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
