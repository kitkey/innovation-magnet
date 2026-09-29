import itertools
from pathlib import Path
import re

from fastapi.testclient import TestClient

from app import llm
from app.engine import offline
from app.engine.offline import MoveAnalysis
from app.main import app
from app.schemas import OpponentState
from app.seeds import SEEDS

FEMININE = re.compile(r"\b(рада|готова|согласна|должна|могла|поняла|услышала|сказала|позвала|поручила|неготовой)\b", re.I)
MASCULINE = re.compile(r"\b(рад|готов|согласен|должен|мог|понял|услышал|сказал|позвал|поручил|неготовым)\b", re.I)
LABELS = ["manipulation", "pressure", "boundary", "conditional_trade", "batna_reference", "concrete_offer", "argument",
          "interest_question", "vague", "accept"]


def _male(sid):
    return SEEDS[sid].model_copy(update={"voice": "male"})


def test_male_seeds_have_male_character_and_texts():
    for sid, name, avatar in (("deadline-with-manager", "Сергей Власов", "/avatars/chibi_b3.glb"),
                              ("price-with-client", "Артур Галиев", "/avatars/chibi_b4.glb")):
        card = SEEDS[sid]
        assert card.voice == "male" and card.opponent_name == name and card.avatar_url == avatar
        text = " ".join([card.context, card.opening, card.opponent_goal, card.opponent_batna, *card.opponent_hidden_interests])
        assert not FEMININE.search(text), FEMININE.search(text)


def test_offline_replies_have_no_gendered_forms_for_either_voice():
    for sid in SEEDS:
        for voice in ("male", "female"):
            card = SEEDS[sid].model_copy(update={"voice": voice})
            for a, b in itertools.combinations(LABELS, 2):
                for conceded in (False, True):
                    r = offline.reply(card, OpponentState(trust=2, position=card.target_zone.opponent_start),
                                      MoveAnalysis(labels=[a, b], mentioned_details=[], proposed_value=None), conceded)
                    assert not FEMININE.search(r) and not MASCULINE.search(r), r


def test_breakdown_reply_follows_voice(monkeypatch):
    with TestClient(app) as c:
        for sid, word, wrong in (("deadline-with-manager", "готов.", "готова"), ("alabuga-workshop-lease", "готова", "готов.")):
            sess = c.post(f"/api/sessions?scenario_id={sid}").json()["session_id"]
            last = None
            for _ in range(6):
                r = c.post(f"/api/sessions/{sess}/turn", json={"message": "Вы некомпетентны, это абсурд и глупость, я вас засужу!"})
                if r.status_code != 200:
                    break
                last = r.json()
                if last["status"] == "finished":
                    break
            assert last and last["outcome"] == "breakdown", last
            assert word in last["opponent_message"] and wrong not in last["opponent_message"]


def test_llm_prompt_gender_matches_voice():
    assert "мужском" in llm._gender(SEEDS["deadline-with-manager"])
    assert "женском" in llm._gender(SEEDS["alabuga-workshop-lease"])


def test_characters_endpoint_and_cardgen_pick():
    from app import characters
    with TestClient(app) as c:
        items = c.get("/api/avatars/characters").json()
    assert {i["id"] for i in items} == {"b1", "b2", "b3", "b4", "a1", "a2", "a3", "a4"}
    assert all(i["ready"] for i in items if i["style"] == "chibi")
    for i in items:
        if i["ready"]:
            assert (Path(__file__).resolve().parents[2] / "frontend" / "public" / i["url"].lstrip("/")).exists(), i["url"]
    for voice in ("male", "female"):
        url = characters.pick(voice, "Иван Петров")
        assert url and next(ch for ch in characters.CHARACTERS if ch.url == url).voice == voice
        assert characters.pick(voice, "Иван Петров") == url
