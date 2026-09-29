"""Целевая зона шкалой вариантов: схема, движок на номерах вариантов, офлайн-распознавание, генератор карточек, сид."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import cardgen, llm, service
from app.cardgen import GeneratedCard, to_card
from app.db import ScenarioRow, SessionLocal
from app.engine import hints, offline, rules
from app.main import app
from app.schemas import MoveAnalysis, OpponentState, ScenarioCard, TargetZone
from app.seeds import SEEDS

CARD = SEEDS["extra-work-clause"]
Z = CARD.target_zone
OPTS = list(Z.options)


def zone(**kw):
    return TargetZone(**({"unit": "пункт о допработах при срыве срока", "options": OPTS, "user_start": 0, "zone_min": 0,
                          "zone_max": 1, "opponent_start": 3} | kw))


def with_zone(**kw) -> ScenarioCard:
    return CARD.model_copy(update={"target_zone": zone(**kw)})


def test_schema_accepts_options_and_formats_text():
    assert Z.ordinal and Z.subject == "пункт о допработах при срыве срока" and Z.short_unit == ""
    assert Z.fmt(3) == f"«{OPTS[3]}»" and Z.fmt_at(1) == f"на варианте «{OPTS[1]}»"
    assert "1) Пункта нет" in Z.numbered() and "целевая зона — варианты 1–2" in Z.describe()
    numeric = SEEDS["supplier-price-batna"].target_zone
    assert not numeric.ordinal and numeric.options == [] and numeric.fmt(3) == "3%" and numeric.fmt_at(10) == "на 10%"


@pytest.mark.parametrize("kw,err", [
    ({"options": ["Один вариант"]}, "от 2 до 8"),
    ({"options": [f"Вариант {i}" for i in range(9)]}, "от 2 до 8"),
    ({"options": ["Предоплата", "предоплата", "Постоплата", "Рассрочка"]}, "совпадают"),
    ({"opponent_start": 4}, "Старт собеседника"),
    ({"zone_max": 1.5}, "Конец зоны"),
    ({"user_start": 3, "opponent_start": 0, "zone_min": 1, "zone_max": 2}, "выше старта собеседника"),
    ({"zone_min": 2, "zone_max": 1}, "больше её конца"),
    ({"user_start": 1, "zone_min": 0}, "между стартовыми"),
])
def test_schema_rejects_bad_options(kw, err):
    with pytest.raises(ValidationError) as e:
        zone(**kw)
    assert err in str(e.value)


def test_blank_options_dropped_and_old_cards_stay_numeric():
    assert zone(options=[*OPTS, "  ", ""]).options == OPTS
    data = SEEDS["deadline-with-manager"].model_dump()
    data["target_zone"].pop("options")
    assert not ScenarioCard(**data).target_zone.ordinal


def test_engine_steps_one_option_and_stops_at_limit():
    assert rules.opponent_limit(CARD) == 0
    assert rules.opponent_limit(CARD.model_copy(update={"difficulty": "hard"})) == 1
    assert rules.opponent_limit(with_zone(zone_max=2)) == 1  # половина пути 0–2 — вариант 1
    state = rules.initial_state(CARD)
    positions = []
    for _ in range(6):
        state, _ = rules.apply_move(CARD, state, MoveAnalysis(labels=["interest_question", "objective_criterion", "empathy"]))
        positions.append(state.position)
    assert positions[0] == 2 and all(p == int(p) for p in positions) and min(positions) == 0 and positions[-1] == 0


def test_plausible_values_are_option_numbers():
    assert rules.is_plausible(CARD, 0) and rules.is_plausible(CARD, 3)
    assert not rules.is_plausible(CARD, 4) and not rules.is_plausible(CARD, 1.5) and not rules.is_plausible(CARD, -1)


def test_agreement_and_zone_on_indices():
    at = OpponentState(position=2)
    offer = lambda v: MoveAnalysis(labels=["concrete_offer"], proposed_value=v)
    assert rules.decide_outcome(CARD, at, offer(0), 1) == (None, None)  # лучше позиции собеседника — не сделка
    assert rules.decide_outcome(CARD, at, offer(2), 1) == ("agreement_out_of_zone", 2)
    assert rules.decide_outcome(CARD, OpponentState(position=1), MoveAnalysis(labels=["accept"]), 1) == ("agreement_in_zone", 1)
    assert rules.decide_outcome(CARD, OpponentState(position=1), offer(1), 1) == ("agreement_in_zone", 1)


def test_walk_away_against_zone_edge():
    assert rules.zone_boundary(CARD) == 1
    assert rules.walk_away_justified(CARD, 3) and rules.walk_away_justified(CARD, 2)
    assert not rules.walk_away_justified(CARD, 1) and not rules.walk_away_justified(CARD, 0)
    ok, note = service.walk_away_verdict(CARD, 3)
    assert ok and f"стоял на варианте «{OPTS[3]}»" in note and f"({'«' + OPTS[1] + '»'})" in note


@pytest.mark.parametrize("text,idx", [
    ("Давайте уберём этот пункт из договора", 0),
    ("Допработы будете оплачивать отдельно", 0),
    ("Предлагаю ограничить допработы пятью рабочими днями", 1),
    ("Допработы не больше 5 рабочих дней", 1),
    ("Давайте так: допработы за наш счёт, но с лимитом в пять дней", 1),
    ("Готовы на допработы без лимита, но без штрафа", 2),
    ("Согласен на штраф", 3),
    ("Вариант 2 нас устроит", 1),
    ("Второй вариант подходит", 1),
    ("Этот пункт для нас неприемлем", None),
    ("Что для вас важно в сроках?", None),
])
def test_offline_recognizes_option_by_keywords(text, idx):
    assert offline.option_index(Z, text) == idx
    assert offline.analyze(CARD, text).proposed_value == (None if idx is None else float(idx))


def test_offline_other_option_sets():
    pay = TargetZone(unit="схема оплаты проекта", options=["Предоплата 100 %", "Предоплата 50 %, остальное после сдачи", "Оплата после сдачи"],
                     user_start=0, zone_min=0, zone_max=1, opponent_start=2)
    assert offline.option_index(pay, "Давайте 50 % вперёд") == 1
    assert offline.option_index(pay, "Нам удобнее оплата после сдачи всей работы") == 2
    assert offline.option_index(pay, "Предоплата обязательна") == 0  # предоплата без суммы — полная
    assert offline.option_index(pay, "Нужна гарантия") is None
    work = TargetZone(unit="формат работы", options=["Удалёнка", "Гибрид: два дня в офисе", "Офис пять дней"],
                      user_start=0, zone_min=0, zone_max=1, opponent_start=2)
    assert offline.option_index(work, "Я готов работать удалённо") == 0
    assert offline.option_index(work, "Гибридный формат подойдёт") == 1


def test_unrecognized_option_keeps_position():
    move = offline.analyze(CARD, "Давайте договоримся по-хорошему")
    state, _ = rules.apply_move(CARD, rules.initial_state(CARD), move)
    assert move.proposed_value is None and state.position == 3
    assert rules.decide_outcome(CARD, state, move, 1) == (None, None)


def test_offline_texts_show_option_words():
    r = offline.reply(CARD, OpponentState(position=3), MoveAnalysis(labels=["boundary", "conditional_trade"]), False)
    assert f"Пока я на варианте «{OPTS[3]}»" in r
    assert OPTS[3] in service._template_opening(CARD) and service.opening_ok(CARD, service._template_opening(CARD))
    report = offline.judge_offline(CARD, [("Ну не знаю", MoveAnalysis(labels=["vague"]))])
    assert "единицах торга" not in " ".join(m.better for m in report.key_moments)
    texts = [h.text for _, h, _ in hints.catalog(CARD.model_copy(update={"method": "free"}), False)]
    assert not any("своё число" in t for t in texts)


def test_llm_prompts_list_options_and_number_conversion():
    assert OPTS[0] in llm._subject_line(CARD) and "номер варианта" in llm._subject_line(CARD)
    assert "Единица торга" in llm._subject_line(SEEDS["supplier-price-batna"])
    line = llm._position_line(CARD, OpponentState(position=2))
    assert "вариант 3" in line and OPTS[2] in line
    conv = lambda v: llm.option_number_to_index(CARD, MoveAnalysis(labels=["concrete_offer"], proposed_value=v)).proposed_value
    assert conv(2) == 1 and conv(1) == 0 and conv(5) is None and conv(0) is None and conv(2.5) is None and conv(None) is None
    numeric = SEEDS["supplier-price-batna"]
    assert llm.option_number_to_index(numeric, MoveAnalysis(labels=[], proposed_value=5)).proposed_value == 5


def test_guard_rejects_better_option_in_reply():
    state = OpponentState(position=2)
    assert service._guard_reply(CARD, state, "Без штрафа можно, но допработы за свой счёт без лимита остаются.")
    assert not service._guard_reply(CARD, state, "Ладно, уберём пункт совсем.")


def raw(**z):
    zone = {"player_wants": "less", "unit": "пункт о допработах при срыве срока", "options": OPTS,
            "user_start": 1, "zone_min": 1, "zone_max": 2, "opponent_start": 4}
    return {
        "title": "Пункт о допработах", "domain": "Проектная работа", "topic": "Заказчик хочет штраф за срыв срока",
        "user_role": "Руководитель студии", "user_goal": "Убрать пункт или ограничить пятью днями",
        "opponent_role": "Руководитель проектного офиса", "opponent_name": "Глеб Сомов", "voice": "male",
        "opponent_goal": "Оставить допработы и штраф", "opponent_hidden_interests": ["юристы требуют пункт"],
        "user_batna": "Заказ сети клиник", "opponent_batna": "Вторая студия из тендера",
        "target_zone": zone | z, "context": "Вы руководите студией.", "mandatory_details": ["задержка API"],
        "opening": "Пункт оставляем: допработы за ваш счёт и штраф 0,1 % в день.",
    }


def test_cardgen_options_convert_to_zero_based():
    card = to_card(GeneratedCard(**raw()))
    z = card.target_zone
    assert z.options == OPTS and (z.user_start, z.zone_min, z.zone_max, z.opponent_start) == (0, 0, 1, 3)
    assert card.opening.startswith("Пункт оставляем")


def test_cardgen_options_fixes_and_errors():
    fixed = GeneratedCard(**raw(zone_min=2, zone_max=1, user_start=2, player_wants="more", options="1) Пункта нет\n2) Пять дней\n3) Без лимита\n4) Штраф")).target_zone
    assert fixed.options == ["Пункта нет", "Пять дней", "Без лимита", "Штраф"] and (fixed.zone_min, fixed.zone_max, fixed.user_start) == (1, 2, 1)
    assert fixed.player_wants == "less"
    for z, err in (({"opponent_start": 5}, "от 1 до 4"), ({"user_start": 0}, "от 1 до 4"), ({"user_start": 4, "opponent_start": 1, "zone_min": 2, "zone_max": 3}, "порядок options"),
                   ({"zone_max": 4}, "включает старт собеседника"), ({"options": ["Один"]}, "от 2 до 8"), ({"options": ["А вариант", "а вариант"]}, "одинаковые"),
                   ({"zone_min": 1.5}, "номер варианта")):
        with pytest.raises(ValidationError) as e:
            GeneratedCard(**raw(**z))
        assert err in str(e.value), (z, str(e.value))


def test_cardgen_opening_must_name_opponent_option():
    assert to_card(GeneratedCard(**raw() | {"opening": "Давайте просто уберём пункт, он лишний."})).opening == ""
    assert to_card(GeneratedCard(**raw() | {"opening": "Обсудим договор?"})).opening == ""


def test_cardgen_prompt_explains_options():
    prompt = cardgen.system_prompt()
    assert "options" in prompt and "от лучшего для игрока к худшему" in prompt and "Предоплата 50 %" in prompt


def test_numeric_cards_untouched_by_options_path():
    zone = {"player_wants": "less", "unit": "стоимость сайта, тыс. руб.", "user_start": 120, "zone_min": 130, "zone_max": 150, "opponent_start": 180}
    g = GeneratedCard(**raw() | {"target_zone": zone, "opening": "Смета у вас: 180 тысяч."})
    assert not to_card(g).target_zone.ordinal and to_card(g).opening.startswith("Смета")


def test_seed_loads_into_existing_db_and_plays_offline():
    with TestClient(app):
        pass
    with SessionLocal() as db:  # база уже была: удаляем новый сид, как будто её создали до него
        db.delete(db.get(ScenarioRow, "extra-work-clause"))
        db.commit()
    with TestClient(app) as client:
        assert "extra-work-clause" in {s["id"] for s in client.get("/api/scenarios").json()}
        sc = client.get("/api/scenarios").json()
        seed = next(s for s in sc if s["id"] == "extra-work-clause")
        assert seed["target_zone"]["options"] == OPTS
        sid = client.post("/api/sessions", params={"scenario_id": "extra-work-clause"}).json()["session_id"]
        msgs = ["Понимаю, почему пункт в шаблоне. Что для вас важнее: сам штраф или запуск к распродаже?",
                "Задержка API на стороне заказчика уже неделя, это факт. Какие у вас ограничения по договору?",
                "Рыночный стандарт для таких проектов — ограничить ответственность. Если вы ограничите допработы, мы дадим понедельный график сдачи этапов.",
                "Для нас важен запуск в срок так же, как для вас. Что если зафиксировать понедельный график сдачи этапов и отчёт?",
                "Предлагаю: допработы за наш счёт, но не больше 5 рабочих дней, без штрафа."]
        last = None
        for m in msgs:
            last = client.post(f"/api/sessions/{sid}/turn", json={"message": m}).json()
            if last["status"] == "finished":
                break
        assert last["outcome"] == "agreement_in_zone", last
        res = client.get(f"/api/sessions/{sid}/result").json()
        assert res["final_position"] == 1 and res["in_zone"] is True and "Договорились" in last["opponent_message"]
        assert OPTS[1] in last["opponent_message"]


def test_walk_away_session_on_options():
    with TestClient(app) as client:
        _walk_away(client)


def _walk_away(client):
    sid = client.post("/api/sessions", params={"scenario_id": "extra-work-clause"}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/turn", json={"message": "У нас есть альтернатива: заказ сети клиник без штрафов."})
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": "Мы отказываемся от сделки и переходим к альтернативе."}).json()
    assert r["outcome"] == "walk_away"
    res = client.get(f"/api/sessions/{sid}/result").json()
    assert res["walk_away_justified"] is True and OPTS[3] in res["walk_away_note"]
