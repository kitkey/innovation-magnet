from app import llm
from app.config import settings


def test_cardgen_uses_pro_when_main_is_lite(monkeypatch):
    monkeypatch.setattr(settings, "llm_cardgen_model", "")
    monkeypatch.setattr(settings, "llm_model", "openai/gpt://b1g/yandexgpt-lite/latest")
    assert llm.cardgen_model() == "openai/gpt://b1g/yandexgpt/latest"


def test_cardgen_explicit_model_wins(monkeypatch):
    monkeypatch.setattr(settings, "llm_cardgen_model", "openai/gpt://b1g/yandexgpt/rc")
    monkeypatch.setattr(settings, "llm_model", "openai/gpt://b1g/yandexgpt-lite/latest")
    assert llm.cardgen_model() == "openai/gpt://b1g/yandexgpt/rc"


def test_cardgen_other_provider_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "llm_cardgen_model", "")
    monkeypatch.setattr(settings, "llm_model", "openrouter/qwen/qwen3.8-27b:free")
    assert llm.cardgen_model() == "openrouter/qwen/qwen3.8-27b:free"
