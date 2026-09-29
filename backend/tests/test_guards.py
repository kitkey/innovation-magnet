"""Страховки поверх разметки LLM: метки исхода только при явных словах, значение только из текста игрока,
вопрос не бывает предложением, давление по маркерам важнее меток LLM, собеседник не говорит словами игрока."""
import pytest
from fastapi.testclient import TestClient

from app import llm, service
from app.config import settings
from app.engine import guards, rules
from app.main import app
from app.schemas import MoveAnalysis, OpponentState
from app.seeds import SEEDS

ALABUGA = SEEDS["alabuga-workshop-lease"]
SUPPLIER = SEEDS["supplier-price-batna"]
DEADLINE = SEEDS["deadline-with-manager"]
CLAUSE = SEEDS["extra-work-clause"]


def fix(card, text, labels, value=None, details=None):
    raw = MoveAnalysis(labels=labels, proposed_value=value, mentioned_details=details or [])
    return guards.reconcile(card, text, raw, card.target_zone.opponent_start)


def ends(card, move):
    state, _ = rules.apply_move(card, rules.initial_state(card), move)
    return rules.decide_outcome(card, state, move, 1)[0]


def test_question_about_deadline_is_not_an_offer():
    """Живой случай на Lite: вопрос о сроке размечен предложением 10% и закрыл сессию «соглашением вне зоны»."""
    text = "Хорошо, что цех подошёл. К какому сроку нужно запустить производство?"
    for labels in (["concrete_offer"], ["accept", "batna_reference"], ["concession", "boundary", "walk_away"]):
        m = fix(ALABUGA, text, labels, 10)
        assert not set(m.labels) & {"concrete_offer", "accept", "walk_away", "concession", "boundary", "batna_reference"}
        assert m.proposed_value is None
        assert set(m.labels) & guards.QUESTIONS
        assert ends(ALABUGA, m) is None


def test_invented_value_is_dropped():
    m = fix(ALABUGA, "Мы можем подключить мощность по тарифу за шесть недель.", ["concrete_offer"], 10)
    assert m.proposed_value is None
    assert "concrete_offer" not in m.labels
    assert ends(ALABUGA, m) is None


@pytest.mark.parametrize("text, value", [
    ("Предлагаю скидку 2% к базовой ставке.", 2),
    ("Предлагаю скидку в два процента.", 2),
    ("Готовы дать три процента при договоре на пять лет.", 3),
])
def test_value_named_by_player_is_kept(text, value):
    m = fix(ALABUGA, text, ["conditional_trade"], value)
    assert m.proposed_value == value
    assert "concrete_offer" in m.labels


def test_value_taken_from_text_when_llm_named_another():
    m = fix(SUPPLIER, "Предлагаю рост 3%, и подписываем объём на год.", ["concrete_offer"], 10)
    assert m.proposed_value == 3


def test_opponent_number_repeated_is_not_a_deal():
    """Игрок повторил число собеседника без согласия: предложение, которое закрыло бы сделку, не засчитывается."""
    for text in ("Вы просите 10% — это много для нас.", "Готовы обсудить, почему 10% для вас важны."):
        m = fix(ALABUGA, text, ["concrete_offer"], 10)
        assert ends(ALABUGA, m) is None
    m = fix(ALABUGA, "Ладно, давайте 10%, подписываем.", ["concrete_offer"], 10)
    assert ends(ALABUGA, m) == "agreement_out_of_zone"


def test_rhetorical_question_with_opponent_number():
    m = fix(ALABUGA, "Вы серьёзно думаете, что мы дадим 10%? Это смешно.", ["concrete_offer", "conditional_trade"], 10)
    assert "pressure" in m.labels
    assert not set(m.labels) & {"concrete_offer", "conditional_trade", "accept"}
    assert ends(ALABUGA, m) is None


@pytest.mark.parametrize("text", [
    "Хорошо, договорились.", "По рукам: 10% к окладу.", "Согласен на ваши условия.", "Давайте так и сделаем.",
    "Идёт, подписываем.", "Нас это устраивает.",
])
def test_explicit_accept(text):
    assert guards.explicit_accept(text)


@pytest.mark.parametrize("text", [
    "Хорошо, что цех подошёл.", "Не согласен, это слишком мало.", "Вас устраивает такой вариант?",
    "Согласен, но только при отгрузке за 3 дня.", "Речь идёт о большом объёме.", "Нас не устраивает рост 10%.",
])
def test_not_accept(text):
    assert not guards.explicit_accept(text)


def test_accept_without_consent_words_is_dropped():
    m = fix(DEADLINE, "Хорошо, что вы готовы обсуждать срок. Что будет, если отчёт придёт позже?", ["accept"], 5)
    assert "accept" not in m.labels
    assert ends(DEADLINE, m) is None
    m = fix(DEADLINE, "Хорошо, договорились, делаю к пятнице.", ["accept"])
    assert ends(DEADLINE, m) == "agreement_out_of_zone"


@pytest.mark.parametrize("text", [
    "Тогда мы прекращаем переговоры и отдаём цех следующей компании из очереди.",
    "Мы переходим к резервному поставщику, на этом всё.",
    "Я принимаю второй оффер, спасибо за время.",
    "Тогда без сделки.",
    "Отказываемся от контракта.",
])
def test_explicit_walk_away(text):
    assert guards.explicit_walk_away(text)


@pytest.mark.parametrize("text", [
    "Извините, если прозвучало резко. Расскажите, что для вас сейчас самое важное?",
    "Если не договоримся, нам придётся перейти к резервному поставщику.",
    "Может, перейдём к другому вопросу?",
    "Мы не прекращаем переговоры, давайте искать вариант.",
    "Либо вы берёте цех, либо он уходит следующей компании.",
])
def test_not_walk_away(text):
    assert not guards.explicit_walk_away(text)


def test_apology_is_not_walk_away():
    """Живой случай: извинение с вопросом об интересах размечено выходом и закрыло сессию."""
    text = "Извините, если прозвучало резко. Расскажите, что для вас сейчас самое важное в этом проекте?"
    m = fix(ALABUGA, text, ["walk_away", "pressure"])
    assert "walk_away" not in m.labels and "pressure" not in m.labels
    assert "empathy" in m.labels
    assert ends(ALABUGA, m) is None


def test_conditional_threat_is_batna_reference():
    m = fix(SUPPLIER, "Если не снизите цену, мы откажемся от сделки и перейдём к резервному поставщику.", ["walk_away"])
    assert "walk_away" not in m.labels
    assert "batna_reference" in m.labels


def test_pressure_by_markers_wins_over_trade_and_interest():
    """Живой случай: ультиматум размечен «обменом условиями» и «сравнением с альтернативой», доверие росло."""
    text = "Либо вы берёте цех по нашей ставке, либо он уходит следующей компании из очереди. Решайте быстро."
    m = fix(ALABUGA, text, ["conditional_trade", "interest_question", "batna_reference"])
    assert "pressure" in m.labels
    assert not set(m.labels) & {"conditional_trade", "interest_question"}
    state, _ = rules.apply_move(ALABUGA, rules.initial_state(ALABUGA), m)
    assert state.trust < 0


def test_unsupported_batna_and_trade_are_dropped():
    m = fix(ALABUGA, "Понимаю, для вас сроки запуска критичны.", ["batna_reference", "concession", "conditional_trade"], 10)
    assert m.labels == ["empathy"]
    assert m.proposed_value is None


def test_details_need_words_in_text():
    m = fix(ALABUGA, "К какому сроку нужно запустить производство?", ["spin_situation", "mandatory_detail"],
            details=["льготы резидента"])
    assert m.mentioned_details == [] and "mandatory_detail" not in m.labels
    m = fix(ALABUGA, "Подключим мощность за шесть недель по тарифу.", ["argument"])
    assert m.mentioned_details == ["подключение мощности за шесть недель"]


def test_ordinal_value_needs_recognized_option():
    m = fix(CLAUSE, "Давайте ограничим допработы пятью рабочими днями без штрафа.", ["conditional_trade"], 1)
    assert m.proposed_value == 1 and "concrete_offer" in m.labels
    m = fix(CLAUSE, "Почему для вас так важен этот пункт?", ["concrete_offer"], 3)
    assert m.proposed_value is None and "concrete_offer" not in m.labels
    m = fix(CLAUSE, "Давайте обсудим сроки сдачи этапов.", ["concrete_offer"], 2)
    assert m.proposed_value is None


def test_spelled_numbers_need_unit():
    assert guards.spell_digits("скидка в два процента") == "скидка в 2 процента"
    assert guards.spell_digits("двадцать пять тысяч") == "25 тысяч"
    assert guards.spell_digits("два варианта") == "два варианта"


def test_strip_player_voice():
    player = "Мы не можем отступить от регламента: скидка больше 3% без инвесткомитета невозможна."
    reply = "Мы не можем отступить от регламента: скидка больше 3% без инвесткомитета невозможна. Тогда нам нужна хотя бы быстрая мощность."
    assert guards.strip_player_voice(reply, [player]) == "Тогда нам нужна хотя бы быстрая мощность."
    assert guards.strip_player_voice("Понятно. Пользователь: а если 5%?", [player]) == "Понятно."
    assert guards.strip_player_voice("Регламент я понимаю, но 3% нам мало.", [player]) == "Регламент я понимаю, но 3% нам мало."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_turn_with_bad_llm_labels_keeps_session_open(client, monkeypatch):
    monkeypatch.setattr(settings, "offline_mode", False)
    monkeypatch.setattr(llm, "analyze_move", lambda card, history, message: MoveAnalysis(labels=["concrete_offer", "accept"], proposed_value=10))
    monkeypatch.setattr(llm, "opponent_reply", lambda *a: "К ноябрю. Хорошо, что цех подошёл. К какому сроку нужно запустить производство?")
    sid = client.post("/api/sessions", params={"scenario_id": "alabuga-workshop-lease"}).json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": "Хорошо, что цех подошёл. К какому сроку нужно запустить производство?"}).json()
    assert r["status"] == "active" and r["outcome"] is None
    assert r["analysis"]["proposed_value"] is None
    assert r["opponent_message"] == "К ноябрю."


def test_judge_gets_used_techniques():
    line = llm.used_techniques([{"role": "opponent", "text": "…"}, {"role": "user", "text": "?", "labels": ["spin_situation"]},
                                {"role": "user", "text": "!", "labels": []}])
    assert "ход 1: вопрос о ситуации" in line and "ход 2: без приёмов" in line


def test_label_model_setting(monkeypatch):
    monkeypatch.setattr(settings, "llm_label_model", "")
    assert llm.label_model() == settings.llm_model
    monkeypatch.setattr(settings, "llm_label_model", "openai/gpt://x/yandexgpt/latest")
    assert llm.label_model() == "openai/gpt://x/yandexgpt/latest"


def test_reconcile_on_offline_state_position():
    """Позиция собеседника после уступок: 3% при позиции 3 уже закрывает сделку и требует явного предложения."""
    raw = MoveAnalysis(labels=["concrete_offer"], proposed_value=3)
    m = guards.reconcile(ALABUGA, "3% — это то, о чём мы говорили.", raw, 3)
    assert "concrete_offer" not in m.labels
    m = guards.reconcile(ALABUGA, "Предлагаю 3% и подписываем.", raw, 3)
    assert rules.decide_outcome(ALABUGA, OpponentState(position=3), m, 1)[0] == "agreement_in_zone"


def test_accept_added_by_markers_and_trade_by_markers():
    m = fix(DEADLINE, "Хорошо, договорились, делаю к пятнице.", ["spin_situation"])
    assert "accept" in m.labels
    m = fix(DEADLINE, "Хорошо, договорились созвониться завтра.", ["argument"])
    assert "accept" not in m.labels
    m = fix(ALABUGA, "Если вы подпишете договор на пять лет, мы дадим скидку 3%.", ["option_generation"], 3)
    assert "conditional_trade" in m.labels and m.proposed_value == 3


def test_statement_is_not_a_question_and_if_with_value_is_trade():
    text = "Мы можем подключить 2 МВт за шесть недель по тарифу. Если подпишете договор на пять лет, дадим скидку 3%."
    m = fix(ALABUGA, text, ["spin_situation", "interest_question", "concrete_offer"], 3)
    assert not set(m.labels) & guards.QUESTIONS
    assert "conditional_trade" in m.labels and m.proposed_value == 3
    m = fix(ALABUGA, "Расскажите, что для вас важно в этом проекте.", ["interest_question"])
    assert "interest_question" in m.labels
