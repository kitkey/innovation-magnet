import base64
import io
import json
import math
import struct
import wave

import pytest
from fastapi.testclient import TestClient

from app import voice
from app.config import settings
from app.main import app
from app.schemas import OpponentState
from app.seeds import SEEDS
from app.yandex import stt_pb2 as pb

DEADLINE = SEEDS["deadline-with-manager"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "test-key")


def make_wav(seconds=1.0, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) * channels for i in range(n)))
    return buf.getvalue()


def make_glb(doc: dict, length_delta: int = 0) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js
    return b"glTF" + struct.pack("<II", 2, 12 + len(body) + length_delta) + body


GOOD_GLB = {"asset": {"version": "2.0"}, "nodes": [{"name": "Armature"}, {"name": "Head"}],
            "meshes": [{"extras": {"targetNames": ["viseme_aa", "viseme_PP", "eyeBlinkLeft"]}, "primitives": []}]}


def start(client, scenario="deadline-with-manager"):
    return client.post("/api/sessions", params={"scenario_id": scenario}).json()["session_id"]


def stt_responses(*pairs):
    """pairs: (сырой текст финала, нормализованный текст) — как отвечает Yandex STT v3 при включённой нормализации."""
    out = []
    for i, (raw, norm) in enumerate(pairs):
        out.append(pb.StreamingResponse(final=pb.AlternativeUpdate(alternatives=[pb.Alternative(text=raw)]), audio_cursors=pb.AudioCursors(final_index=i)))
        if norm is not None:
            out.append(pb.StreamingResponse(final_refinement=pb.FinalRefinement(final_index=i, normalized_text=pb.AlternativeUpdate(alternatives=[pb.Alternative(text=norm)]))))
    return out


def tts_body(pcm: bytes, words: list[tuple[str, int, int]]) -> str:
    """Ответ REST-шлюза TTS v3: построчные JSON-объекты, int64 строками, как в proto3 JSON."""
    half = len(pcm) // 2 // 2 * 2
    lines = [{"result": {"audioChunk": {"data": base64.b64encode(pcm[:half]).decode()}, "textChunk": {"text": "x"}, "startMs": "0",
                         "wordTimings": [{"word": w, "startMs": str(s), "lengthMs": str(n)} for w, s, n in words]}},
             {"result": {"audioChunk": {"data": base64.b64encode(pcm[half:]).decode()}}}]
    return "\n".join(json.dumps(x) for x in lines)


# ---------- амплуа по состоянию ----------

def test_mood_by_outcome_and_counters():
    s = OpponentState(position=5)
    assert voice.mood_for(DEADLINE, s) == "neutral"
    assert voice.mood_for(DEADLINE, s, "breakdown") == "angry"
    assert voice.mood_for(DEADLINE, s, "agreement_in_zone") == "happy"
    assert voice.mood_for(DEADLINE, s, "turn_limit") == "sad"
    limit = voice.rules.DIFFICULTY[DEADLINE.difficulty]["breakdown_irritation"]
    assert voice.mood_for(DEADLINE, OpponentState(position=5, irritation=math.ceil(0.6 * limit))) == "angry"
    assert voice.mood_for(DEADLINE, OpponentState(position=5, irritation=1)) == "neutral"
    assert voice.mood_for(DEADLINE, OpponentState(position=5, trust=-3)) == "disgust"
    assert voice.mood_for(DEADLINE, OpponentState(position=5, trust=3)) == "happy"


def test_hard_scenario_gets_angry_earlier():
    hard = DEADLINE.model_copy(update={"difficulty": "hard"})
    easy = DEADLINE.model_copy(update={"difficulty": "easy"})
    s = OpponentState(position=5, irritation=3)
    assert voice.mood_for(hard, s) == "angry" and voice.mood_for(easy, s) == "neutral"


def test_voice_and_role_by_mood():
    assert voice.voice_for("female", "angry") == ("jane", "evil", 1.05)
    assert voice.voice_for("female", "happy")[:2] == ("jane", "good")
    assert voice.voice_for("male", "angry")[:2] == ("kirill", "strict")
    assert voice.voice_for("male", "happy")[:2] == ("kirill", "good")
    assert voice.voice_for("male", "sad") == ("kirill", "neutral", 0.9)
    assert voice.voice_for("female", "unknown")[:2] == ("jane", "neutral")


def test_turn_returns_mood(client):
    sid = start(client)
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": "Что для вас важно в этом отчёте?"})
    assert r.status_code == 200 and r.json()["mood"] in ("neutral", "happy", "angry", "sad", "disgust")
    assert client.get(f"/api/sessions/{sid}").json()["mood"] == r.json()["mood"]


# ---------- без ключей ----------

def test_status_without_keys(client):
    st = client.get("/api/voice/status").json()
    assert st["stt"] is False and st["tts"] is False and st["provider"] is None and st["max_seconds"] == 30


def test_voice_turn_without_keys_is_clear_503(client):
    sid = start(client)
    r = client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", make_wav(), "audio/wav")})
    assert r.status_code == 503 and "не настроено" in r.json()["detail"]
    assert client.get(f"/api/sessions/{sid}").json()["turn"] == 0


def test_tts_without_keys_is_503(client):
    r = client.post("/api/tts", json={"text": "Добрый день", "emotion": "angry"})
    assert r.status_code == 503


# ---------- распознавание с моком Yandex ----------

def test_voice_turn_with_mocked_stt(client, keys, monkeypatch):
    sent = []

    def fake_call(requests):
        sent.extend(requests)
        return stt_responses(("понимаю вашу позицию что для вас важно", "Понимаю вашу позицию. Что для вас важно?"))

    monkeypatch.setattr(voice, "_stt_call", fake_call)
    sid = start(client)
    wav = make_wav(1.0)
    r = client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", wav, "audio/wav")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["recognized"] == "Понимаю вашу позицию. Что для вас важно?"
    assert out["turn"] == 1 and out["opponent_message"] and "empathy" in out["analysis"]["labels"]
    assert out["audio_url"].startswith("/uploads/voice/") and client.get(out["audio_url"]).content == wav

    opts = sent[0].session_options.recognition_model
    assert opts.audio_format.raw_audio.sample_rate_hertz == 16000
    assert opts.audio_processing_type == pb.RecognitionModelOptions.FULL_DATA
    assert list(opts.language_restriction.language_code) == ["ru-RU"]
    assert sum(len(x.chunk.data) for x in sent[1:]) == 16000 * 2

    msgs = client.get(f"/api/sessions/{sid}").json()["messages"]
    assert msgs[1]["text"] == out["recognized"] and msgs[1]["audio_url"] == out["audio_url"]
    rewound = client.post(f"/api/sessions/{sid}/rewind", json={"turn": 1}).json()
    assert rewound["messages"][1]["audio_url"] == out["audio_url"]


def test_stt_joins_finals_and_prefers_normalized():
    assert voice.stt_text(stt_responses(("сто восемьдесят тысяч", "180 000"), ("за два дня", "за 2 дня"))) == "180 000 за 2 дня"
    assert voice.stt_text(stt_responses(("без нормализации", None))) == "без нормализации"
    assert voice.stt_text([]) == ""


def test_ogg_goes_as_container(keys):
    audio, ext = voice.prepare_audio(b"OggS" + b"\0" * 100)
    assert ext == "ogg" and audio.kind == "ogg"
    req = voice._stt_requests(audio)[0].session_options.recognition_model.audio_format
    assert req.container_audio.container_audio_type == pb.ContainerAudio.OGG_OPUS


def test_stt_failure_is_502_and_turn_not_made(client, keys, monkeypatch):
    def boom(_):
        raise ConnectionError("network down")

    monkeypatch.setattr(voice, "_stt_call", boom)
    sid = start(client)
    r = client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", make_wav(), "audio/wav")})
    assert r.status_code == 502 and "напишите текстом" in r.json()["detail"]
    assert client.get(f"/api/sessions/{sid}").json()["turn"] == 0


def test_rejected_key_names_the_role(keys, monkeypatch):
    class Unauth(Exception):
        def code(self):
            return type("C", (), {"name": "UNAUTHENTICATED"})()

        def details(self):
            return "Unknown api key"

    def boom(_):
        raise Unauth()

    monkeypatch.setattr(voice, "_stt_call", boom)
    with pytest.raises(voice.VoiceError) as e:
        voice.recognize(voice.Audio("pcm", b"\0\0" * 16000))
    assert e.value.status == 502 and "ai.speechkit-stt.user" in e.value.message


def test_silence_is_422(client, keys, monkeypatch):
    monkeypatch.setattr(voice, "_stt_call", lambda _: stt_responses(("", "")))
    sid = start(client)
    r = client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", make_wav(), "audio/wav")})
    assert r.status_code == 422 and "не распознана" in r.json()["detail"]


def test_bad_audio_rejected(client, keys, monkeypatch):
    monkeypatch.setattr(voice, "_stt_call", lambda _: pytest.fail("STT не должен вызываться"))
    sid = start(client)
    assert client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.bin", b"hello world" * 10, "application/octet-stream")}).status_code == 415
    assert client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", make_wav(31, rate=8000), "audio/wav")}).status_code == 413
    assert client.post(f"/api/sessions/{sid}/voice", files={"audio": ("v.wav", b"", "audio/wav")}).status_code == 422


def test_stereo_wav_without_ffmpeg_is_415(keys, monkeypatch):
    monkeypatch.setattr(voice, "ffmpeg_path", lambda: None)
    with pytest.raises(voice.VoiceError) as e:
        voice.prepare_audio(make_wav(1, rate=44100, channels=2))
    assert e.value.status == 415


# ---------- синтез с моком Yandex ----------

def test_tts_with_mocked_yandex(client, keys, monkeypatch):
    calls = []
    pcm = b"\x01\x00" * voice.TTS_RATE  # ровно 1 с

    def fake_call(text, v, role, speed):
        calls.append((text, v, role, speed))
        return tts_body(pcm, [("добрый", 0, 300), ("день", 320, 400)])

    monkeypatch.setattr(voice, "_tts_call", fake_call)
    long_text = "Добрый день, давайте обсудим сроки. " * 10
    r = client.post("/api/tts", json={"text": long_text, "emotion": "angry", "voice": "female"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(calls) == 2 and all(len(c[0]) <= voice.TTS_CHUNK_CHARS for c in calls)
    assert calls[0][1:] == ("jane", "evil", 1.05)
    assert out["voice"] == "jane" and out["role"] == "evil" and out["mood"] == "angry"
    assert out["words"] == ["добрый", "день", "добрый", "день"]
    assert out["wtimes"] == [0, 320, 1000, 1320] and out["wdurations"] == [300, 400, 300, 400]
    assert out["duration_ms"] == 2000
    with wave.open(io.BytesIO(base64.b64decode(out["audio"]))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (voice.TTS_RATE, 1, 2 * voice.TTS_RATE)


def test_tts_male_calm(keys, monkeypatch):
    monkeypatch.setattr(voice, "_tts_call", lambda *a: tts_body(b"\0\0" * 100, []))
    out = voice.synthesize("Хорошо.", "happy", "male")
    assert (out["voice"], out["role"]) == ("kirill", "good") and out["words"] == []


def test_tts_error_object_is_502(keys, monkeypatch):
    monkeypatch.setattr(voice, "_tts_call", lambda *a: json.dumps({"error": {"code": 16, "message": "Unauthenticated"}}))
    with pytest.raises(voice.VoiceError) as e:
        voice.synthesize("Текст", "neutral", "female")
    assert e.value.status == 502 and "Unauthenticated" in e.value.message


def test_split_text_respects_limit():
    text = "Короткая фраза. " + "очень длинное предложение без точек " * 20 + "конец."
    parts = voice.split_text(text)
    assert all(0 < len(p) <= voice.TTS_CHUNK_CHARS for p in parts)
    assert " ".join(parts).split() == text.split()
    assert voice.split_text("Одна фраза.") == ["Одна фраза."]


# ---------- загрузка GLB ----------

def test_glb_upload_valid(client):
    data = make_glb(GOOD_GLB)
    r = client.post("/api/avatars", files={"file": ("me.glb", data, "model/gltf-binary")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["url"].startswith("/uploads/avatars/") and out["url"].endswith(".glb")
    assert out["visemes"] == 2 and out["warnings"] == []
    assert client.get(out["url"]).content == data
    card = SEEDS["deadline-with-manager"].model_dump() | {"avatar_url": out["url"], "voice": "male"}
    saved = client.post("/api/scenarios", json=card)
    assert saved.status_code == 200 and saved.json()["avatar_url"] == out["url"] and saved.json()["voice"] == "male"


def test_glb_without_visemes_warns(client):
    doc = GOOD_GLB | {"meshes": [{"primitives": []}]}
    out = client.post("/api/avatars", files={"file": ("me.glb", make_glb(doc), "model/gltf-binary")}).json()
    assert len(out["warnings"]) == 2 and out["visemes"] == 0


@pytest.mark.parametrize("name,data,code", [
    ("me.glb", b"NOPE" + b"\0" * 40, 422),
    ("me.gltf", make_glb(GOOD_GLB), 415),
    ("me.glb", make_glb(GOOD_GLB, length_delta=8), 422),
    ("me.glb", make_glb({"nodes": [{"name": "Head"}]}), 422),
    ("me.glb", b"glTF" + struct.pack("<II", 1, 20) + b"\0" * 8, 422),
])
def test_glb_upload_invalid(client, name, data, code):
    r = client.post("/api/avatars", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == code, r.text


def test_glb_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "avatar_max_mb", 0)
    r = client.post("/api/avatars", files={"file": ("me.glb", make_glb(GOOD_GLB), "model/gltf-binary")})
    assert r.status_code == 413


def test_avatar_url_must_be_local(client):
    card = SEEDS["deadline-with-manager"].model_dump()
    assert client.post("/api/scenarios", json=card | {"avatar_url": "https://evil.example/x.glb"}).status_code == 422
    assert client.post("/api/scenarios", json=card | {"avatar_url": "/uploads/avatars/../../x.glb"}).status_code == 422
    ok = client.post("/api/scenarios", json=card | {"avatar_url": ""})
    assert ok.status_code == 200 and ok.json()["avatar_url"] is None
