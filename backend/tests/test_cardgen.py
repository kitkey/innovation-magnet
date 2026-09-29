import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import characters
from app import cardgen, llm
from app.cardgen import CardGenError, GeneratedCard, explain, fix_opening, system_prompt, to_card
from app.config import settings
from app.main import app
from app.schemas import ScenarioCard
from app.seeds import SEEDS


def raw(**kw):
    zone = {"player_wants": "less", "unit": "стоимость сайта, тыс. руб.", "user_start": 120, "zone_min": 130, "zone_max": 150, "opponent_start": 180}
    data = {
        "title": "Цена сайта со студией", "domain": "Маркетинг", "topic": "Студия оценила сайт в 180 тыс. руб.",
        "user_role": "Маркетолог сети автомоек", "user_goal": "Уложиться в 130–150 тыс. руб.",
        "opponent_role": "Руководитель веб-студии", "opponent_name": "Глеб Сомов", "voice": "male",
        "opponent_goal": "Получить 180 тыс. руб.", "opponent_hidden_interests": ["два дизайнера без загрузки"],
        "user_batna": "Фрилансер за 110 тыс. руб.", "opponent_batna": "Ждать другого заказа",
        "target_zone": zone, "context": "Вы отвечаете за сайт.", "mandatory_details": ["запуск до сезона"],
        "opening": "Смета у вас: 180 тысяч, и это без запаса.",
    }
    z = kw.pop("zone", {})
    data["target_zone"] = zone | z
    return data | kw


def zone_error(**z) -> str:
    with pytest.raises(ValidationError) as e:
        GeneratedCard(**raw(zone=z))
    return str(e.value)


def test_valid_card_converts():
    card = to_card(GeneratedCard(**raw()))
    assert card.name == "Цена сайта со студией" and card.target_zone.opponent_start == 180
    assert card.opening.startswith("Смета") and card.coach_tips == [] and card.hints == [] and card.avatar_url == characters.pick(card.voice, card.opponent_name)


def test_reversed_zone_is_swapped():
    g = GeneratedCard(**raw(zone={"zone_min": 150, "zone_max": 130}))
    assert (g.target_zone.zone_min, g.target_zone.zone_max) == (130, 150)


def test_zone_beyond_opponent_start_is_rejected():
    assert "выходит за стартовые позиции" in zone_error(zone_min=190, zone_max=200)
    assert "выходит за стартовые позиции" in zone_error(player_wants="more", unit="срок, дней", user_start=10, zone_min=1, zone_max=2, opponent_start=3)


def test_user_start_inside_zone_moves_to_best_edge():
    less = GeneratedCard(**raw(zone={"user_start": 150})).target_zone
    assert (less.user_start, less.zone_min, less.zone_max) == (130, 130, 150)
    more = GeneratedCard(**raw(zone={"player_wants": "more", "unit": "срок, дней", "user_start": 6, "zone_min": 5, "zone_max": 8, "opponent_start": 3})).target_zone
    assert more.user_start == 8


def test_zone_with_opponent_start_is_rejected():
    assert "включает старт собеседника" in zone_error(zone_max=180)
    assert "включает старт собеседника" in zone_error(zone_max=185)


def test_direction_mismatch_is_rejected():
    assert "перепутаны" in zone_error(player_wants="more")
    msg = zone_error(player_wants="more", user_start=3, opponent_start=7, zone_min=4, zone_max=6, unit="срок, рабочих дней")
    assert "user_start должен быть больше opponent_start" in msg and "3 и 7" in msg


def test_equal_starts_and_bad_unit_are_rejected():
    assert "равны" in zone_error(user_start=180)
    assert "unit пустой" in zone_error(unit="  ")
    assert "без запятой" in zone_error(unit="рубли")


def test_enums_lists_and_turns_are_normalized():
    g = GeneratedCard(**raw(difficulty="Сложная", style="жёсткий", tone="Скептичный", method="Свободный", voice="Мужской",
                            mandatory_details="запуск до сезона; блог потом\nзапуск до сезона", max_turns=40))
    assert (g.difficulty, g.style, g.tone, g.method, g.voice) == ("hard", "hard", "skeptical", "free", "male")
    assert g.mandatory_details == ["запуск до сезона", "блог потом"] and g.max_turns == 14


def test_opening_without_start_or_with_signature():
    g = GeneratedCard(**raw())
    assert fix_opening("Руководитель веб-студии: смета 180 тысяч.", g) == "Смета 180 тысяч."
    assert fix_opening("Давайте обсудим смету.", g) == ""
    assert fix_opening("Моя стартовая позиция 180.", g) == ""
    assert fix_opening("«Это 180 000 рублей.»", g) == "Это 180 000 рублей."


def test_name_and_title_confusion_fixed():
    assert to_card(GeneratedCard(**raw(title="Глеб Сомов"))).name == "Студия оценила сайт в 180 тыс. руб."
    assert to_card(GeneratedCard(**raw(opponent_name="Руководитель веб-студии"))).opponent_name == ""


def test_explain_names_missing_field_and_zone_problem():
    data = raw(zone={"zone_min": 190, "zone_max": 200})
    del data["title"]
    with pytest.raises(ValidationError) as e:
        GeneratedCard(**data)
    text = explain(e.value)
    assert "не заполнено поле «название»" in text and "выходит за стартовые позиции" in text and "Value error" not in text


def test_prompt_and_schema_cover_fields_without_ids():
    prompt = system_prompt()
    schema = GeneratedCard.model_json_schema()
    for key in schema["properties"]:
        assert key in prompt
        assert schema["properties"][key].get("description") or "$ref" in schema["properties"][key]
    assert not {"id", "avatar_url", "coach_tips", "hints", "locked_by_org", "name"} & set(schema["properties"])
    assert {"title", "user_role", "opponent_role", "target_zone", "context"} <= set(schema["required"])


def test_generate_endpoint_reports_card_error(monkeypatch):
    def boom(_):
        raise CardGenError("Карточка не собралась: целевая зона 1–2 выходит за стартовые позиции 3 и 7.")
    monkeypatch.setattr(settings, "offline_mode", False)
    monkeypatch.setattr(llm, "generate_card", boom)
    with TestClient(app) as c:
        r = c.post("/api/scenarios/generate", json={"description": "Хочу скидку у поставщика, он даёт мало."})
    assert r.status_code == 422 and "выходит за стартовые позиции" in r.json()["detail"]
    assert cardgen.CardGenError is CardGenError


def test_domain_icon_in_card_and_generation():
    base = SEEDS["supplier-price-batna"].model_dump()
    assert ScenarioCard(**base).domain_icon is None
    assert ScenarioCard(**base | {"domain_icon": ""}).domain_icon is None
    assert ScenarioCard(**base | {"domain_icon": "logistics"}).domain_icon == "logistics"
    with pytest.raises(ValidationError):
        ScenarioCard(**base | {"domain_icon": "rocket"})
    assert to_card(GeneratedCard(**raw(domain_icon="Marketing"))).domain_icon == "marketing"
    assert to_card(GeneratedCard(**raw(domain_icon="rocket"))).domain_icon is None
    assert "everyday" in system_prompt()


def test_domain_icon_saved_via_api():
    card = SEEDS["supplier-price-batna"].model_dump() | {"name": "Значок группы", "domain_icon": "logistics"}
    with TestClient(app) as c:
        s = c.post("/api/scenarios", json=card).json()
        assert s["domain_icon"] == "logistics"
        listed = next(x for x in c.get("/api/scenarios", params={"ids": s["id"]}).json() if x["id"] == s["id"])
        assert listed["domain_icon"] == "logistics"
        assert c.post("/api/scenarios", json=card | {"domain_icon": "rocket"}).status_code == 422
