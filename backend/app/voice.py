"""Голос и аватар: распознавание голосовых реплик и озвучка собеседника через Yandex SpeechKit v3, амплуа по состоянию, загрузка GLB.

Без ключей Yandex распознавание отвечает 503 с понятным текстом, а вместо озвучки фронт проигрывает беззвучный липсинк по тексту.
Распознавание: STT v3 RecognizeStreaming по gRPC, файл целиком одним потоком в режиме FULL_DATA — для реплик до 30 с это надёжнее
асинхронного API, которому нужен бакет Object Storage. Озвучка: TTS v3 utteranceSynthesis по REST, модель general, тайминги слов.
"""
import base64
import hashlib
import io
import json
import logging
import math
import re
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from .config import settings
from .engine import rules
from .schemas import Mood, OpponentState, ScenarioCard

log = logging.getLogger(__name__)

Gender = Literal["female", "male"]

# Голос и амплуа Yandex general по настроению собеседника. У мужских голосов «злого» амплуа нет, раздражение передаёт strict
VOICES: dict[str, dict[str, tuple[str, str]]] = {
    "female": {"angry": ("jane", "evil"), "disgust": ("jane", "neutral"), "happy": ("jane", "good"), "neutral": ("jane", "neutral"), "sad": ("jane", "neutral"), "skeptic": ("jane", "neutral")},
    "male": {"angry": ("kirill", "strict"), "disgust": ("kirill", "strict"), "happy": ("kirill", "good"), "neutral": ("kirill", "neutral"), "sad": ("kirill", "neutral"), "skeptic": ("kirill", "strict")},
}
SPEED = {"angry": 1.05, "sad": 0.9}

STT_HOST = "stt.api.cloud.yandex.net:443"
TTS_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
TTS_RATE = 22050
TTS_CHUNK_CHARS = 240  # лимит TTS v3 — 250 символов на запрос
STT_RATES = (8000, 16000, 48000)
MAX_AUDIO_BYTES = 5 * 1024 * 1024
ALLOWED_VOICE_EXT = {"wav", "ogg", "webm", "mp4", "mp3"}

NOT_CONFIGURED = "Распознавание речи не настроено: администратору нужно задать YANDEX_API_KEY. Пока отвечайте текстом."


class VoiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message



def _normalization(pb):
    """Нормализация распознанного текста (числа цифрами, пунктуация, литературная правка) по умолчанию выключена:
    судья и разбор видят речь как есть, со словами-паразитами. VOICE_TEXT_NORMALIZATION=true включает её."""
    if settings.voice_text_normalization:
        return pb.TextNormalizationOptions(text_normalization=pb.TextNormalizationOptions.TEXT_NORMALIZATION_ENABLED, literature_text=True)
    return pb.TextNormalizationOptions(text_normalization=pb.TextNormalizationOptions.TEXT_NORMALIZATION_DISABLED)

def uploads_dir() -> Path:
    return Path(settings.uploads_dir) if settings.uploads_dir else Path(__file__).resolve().parent.parent / "uploads"


def stt_ready() -> bool:
    return bool(settings.yandex_api_key)


def tts_ready() -> bool:
    return bool(settings.yandex_api_key)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def status() -> dict:
    return {
        "stt": stt_ready(), "tts": tts_ready(), "provider": "yandex" if stt_ready() else None, "ffmpeg": ffmpeg_path() is not None,
        "max_seconds": settings.voice_max_seconds, "avatar_max_mb": settings.avatar_max_mb,
        "tts_fallback": "Без озвучки аватар двигает губами по тексту беззвучно, текст виден субтитром.",
    }


def mood_for(card: ScenarioCard, state: OpponentState, outcome: str | None = None) -> Mood:
    """Настроение собеседника на этом ходу: по исходу, затем по раздражению и доверию относительно порогов сложности.
    Скепсис: доверие ниже нуля при раздражении ниже порога злости."""
    if outcome == "breakdown":
        return "angry"
    if outcome in ("agreement_in_zone", "agreement_out_of_zone"):
        return "happy"
    if outcome in ("turn_limit", "walk_away"):
        return "sad"
    if state.irritation >= max(2, math.ceil(0.6 * rules.DIFFICULTY[card.difficulty]["breakdown_irritation"])):
        return "angry"
    if state.trust <= -1 and state.irritation >= 1:
        return "skeptic"
    if state.trust <= -3:
        return "disgust"
    if state.trust >= 3:
        return "happy"
    return "neutral"


def voice_for(gender: Gender, mood: str) -> tuple[str, str, float]:
    voice, role = VOICES[gender].get(mood, VOICES[gender]["neutral"])
    return voice, role, SPEED.get(mood, 1.0)


def _auth() -> list[tuple[str, str]]:
    meta = [("authorization", f"Api-Key {settings.yandex_api_key}")]
    if settings.yandex_folder_id:
        meta.append(("x-folder-id", settings.yandex_folder_id))
    return meta


# ---------- входное аудио ----------

@dataclass
class Audio:
    kind: Literal["pcm", "ogg"]
    data: bytes
    rate: int = 16000
    seconds: float | None = None


def sniff(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def _read_wav(data: bytes) -> Audio | None:
    """PCM 16 бит моно с частотой, которую принимает STT, идёт как есть; остальное пусть перекодирует ffmpeg."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() not in STT_RATES:
                return None
            frames = w.readframes(w.getnframes())
            return Audio("pcm", frames, w.getframerate(), len(frames) / 2 / w.getframerate())
    except (wave.Error, EOFError) as exc:
        raise VoiceError(422, f"WAV повреждён: {exc}") from exc


def _ffmpeg_wav(data: bytes) -> Audio:
    exe = ffmpeg_path()
    if exe is None:
        raise VoiceError(415, "Этот формат записи сервер не перекодирует: пришлите WAV или OGG/Opus")
    try:
        out = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                             input=data, capture_output=True, timeout=20, check=True).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise VoiceError(422, "Не удалось прочитать запись") from exc
    audio = _read_wav(out)
    if audio is None:
        raise VoiceError(422, "Не удалось прочитать запись")
    return audio


def prepare_audio(data: bytes) -> tuple[Audio, str]:
    """Проверяет размер, формат и длительность записи. Возвращает аудио для STT и расширение исходного файла."""
    if not data:
        raise VoiceError(422, "Пустая запись")
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError(413, "Запись слишком большая")
    kind = sniff(data)
    if kind is None:
        raise VoiceError(415, "Неизвестный формат записи: нужен WAV, OGG/Opus, WebM или MP3")
    if kind == "ogg":
        audio = Audio("ogg", data)
    else:
        audio = (_read_wav(data) if kind == "wav" else None) or _ffmpeg_wav(data)
    if audio.seconds is not None and audio.seconds > settings.voice_max_seconds + 0.5:
        raise VoiceError(413, f"Голосовое длиннее {settings.voice_max_seconds} с, запишите короче")
    if audio.seconds is not None and audio.seconds < 0.3:
        raise VoiceError(422, "Запись слишком короткая")
    return audio, kind


# ---------- распознавание ----------

def _stt_requests(audio: Audio):
    from .yandex import stt_pb2 as pb

    fmt = (pb.AudioFormatOptions(raw_audio=pb.RawAudio(audio_encoding=pb.RawAudio.LINEAR16_PCM, sample_rate_hertz=audio.rate, audio_channel_count=1))
           if audio.kind == "pcm" else pb.AudioFormatOptions(container_audio=pb.ContainerAudio(container_audio_type=pb.ContainerAudio.OGG_OPUS)))
    options = pb.StreamingOptions(recognition_model=pb.RecognitionModelOptions(
        model="general", audio_format=fmt,
        text_normalization=_normalization(pb),
        language_restriction=pb.LanguageRestrictionOptions(restriction_type=pb.LanguageRestrictionOptions.WHITELIST, language_code=["ru-RU"]),
        audio_processing_type=pb.RecognitionModelOptions.FULL_DATA,
    ))
    out = [pb.StreamingRequest(session_options=options)]
    step = 32000
    out += [pb.StreamingRequest(chunk=pb.AudioChunk(data=audio.data[i:i + step])) for i in range(0, len(audio.data), step)]
    return out


def _stt_call(requests: list):
    """Один gRPC-поток к Yandex STT v3. В тестах подменяется."""
    import grpc

    from .yandex import stt_service_pb2_grpc

    with grpc.secure_channel(STT_HOST, grpc.ssl_channel_credentials()) as channel:
        stub = stt_service_pb2_grpc.RecognizerStub(channel)
        return list(stub.RecognizeStreaming(iter(requests), metadata=_auth(), timeout=settings.voice_timeout))


def stt_text(responses) -> str:
    """Склеивает финалы по порядку; нормализованный текст (числа цифрами) берём, если он пришёл на каждый финал."""
    finals, refined = [], []
    for r in responses:
        event = r.WhichOneof("Event")
        if event == "final" and r.final.alternatives:
            finals.append(r.final.alternatives[0].text)
        elif event == "final_refinement" and r.final_refinement.normalized_text.alternatives:
            refined.append(r.final_refinement.normalized_text.alternatives[0].text)
    texts = refined if refined and len(refined) >= len(finals) else finals
    return re.sub(r"\s+", " ", " ".join(t.strip() for t in texts)).strip()


def recognize(audio: Audio) -> str:
    if not stt_ready():
        raise VoiceError(503, NOT_CONFIGURED)
    try:
        responses = _stt_call(_stt_requests(audio))
    except ImportError as exc:
        raise VoiceError(503, "На сервере не установлен grpcio, распознавание недоступно") from exc
    except Exception as exc:  # grpc.RpcError и сетевые ошибки
        code = getattr(exc, "code", None)
        name = code().name if callable(code) else ""
        log.warning("Yandex STT failed: %s %s", name, exc.details() if callable(getattr(exc, "details", None)) else exc)
        if name in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            raise VoiceError(502, "Yandex не принял ключ распознавания: проверьте YANDEX_API_KEY и роль ai.speechkit-stt.user. Пока напишите текстом") from exc
        raise VoiceError(502, "Сервис распознавания не ответил. Попробуйте ещё раз или напишите текстом") from exc
    return stt_text(responses)


# ---------- синтез ----------

def split_text(text: str, limit: int = TTS_CHUNK_CHARS) -> list[str]:
    """Режет текст на куски до limit символов: по предложениям, длинное предложение — по запятым и пробелам."""
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        pieces = [sentence]
        while len(pieces[-1]) > limit:
            s = pieces.pop()
            cut = max(s.rfind(", ", 0, limit), s.rfind(" ", 0, limit))
            cut = cut if cut > 0 else limit
            pieces += [s[:cut + 1].strip(), s[cut + 1:].strip()]
        for p in pieces:
            if cur and len(cur) + 1 + len(p) > limit:
                parts.append(cur)
                cur = p
            else:
                cur = f"{cur} {p}".strip()
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def _ms(v) -> int:
    return int(float(v or 0))


def parse_tts(body: str) -> tuple[bytes, list[tuple[str, int, int]]]:
    """Ответ REST-шлюза — поток JSON-объектов {"result": {...}} построчно (иногда массивом). Собираем PCM и тайминги слов."""
    body = body.strip()
    try:
        objs = [json.loads(line) for line in body.splitlines() if line.strip()]
    except json.JSONDecodeError:
        objs = json.loads(body)
    if len(objs) == 1 and isinstance(objs[0], list):
        objs = objs[0]
    pcm, words = bytearray(), []
    for o in objs:
        if "error" in o:
            raise VoiceError(502, f"Сервис синтеза вернул ошибку: {o['error'].get('message', o['error'])}")
        res = o.get("result", o)
        chunk = res.get("audioChunk") or res.get("audio_chunk") or {}
        if chunk.get("data"):
            pcm += base64.b64decode(chunk["data"])
        for w in res.get("wordTimings") or res.get("word_timings") or []:
            words.append((w.get("word", ""), _ms(w.get("startMs", w.get("start_ms"))), _ms(w.get("lengthMs", w.get("length_ms")))))
    return bytes(pcm), words


def _tts_call(text: str, voice: str, role: str, speed: float) -> str:
    """Один запрос к Yandex TTS v3. В тестах подменяется."""
    body = {
        "text": text, "hints": [{"voice": voice}, {"role": role}, {"speed": speed}],
        "outputAudioSpec": {"rawAudio": {"audioEncoding": "LINEAR16_PCM", "sampleRateHertz": TTS_RATE}},
        "loudnessNormalizationType": "LUFS",
    }
    r = httpx.post(TTS_URL, json=body, headers=dict(_auth()), timeout=settings.voice_timeout)
    if r.status_code != 200:
        log.warning("Yandex TTS failed: %s %s", r.status_code, r.text[:300])
        if r.status_code in (401, 403):
            raise VoiceError(502, "Yandex не принял ключ синтеза: проверьте YANDEX_API_KEY и роль ai.speechkit-tts.user")
        raise VoiceError(502, f"Сервис синтеза ответил {r.status_code}")
    return r.text


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _tts_cache_path(text: str, voice: str, role: str, speed: float) -> Path:
    key = hashlib.sha256(f"{voice}|{role}|{speed}|{text}".encode()).hexdigest()[:32]
    return uploads_dir() / "tts_cache" / f"{key}.json"


def synthesize(text: str, mood: str, gender: Gender) -> dict:
    """Озвучка реплики. Одинаковый текст с тем же голосом, амплуа и скоростью синтезируется один раз и дальше берётся
    с диска: переигровка, повтор входа в диалог и перезапуск сервера не стоят новых запросов к Yandex."""
    if not tts_ready():
        raise VoiceError(503, "Озвучка не настроена: нужен YANDEX_API_KEY")
    voice, role, speed = voice_for(gender, mood)
    cached = _tts_cache_path(text, voice, role, speed)
    if cached.is_file():
        try:
            return {**json.loads(cached.read_text(encoding="utf-8")), "mood": mood, "cached": True}
        except (OSError, json.JSONDecodeError):
            pass
    out = _synthesize(text, voice, role, speed)
    out["mood"] = mood
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("TTS cache write failed: %s", exc)
    return out


def _synthesize(text: str, voice: str, role: str, speed: float) -> dict:
    pcm, words, wtimes, wdurations = bytearray(), [], [], []
    try:
        for part in split_text(text):
            offset = len(pcm) * 1000 // (2 * TTS_RATE)
            chunk, timings = parse_tts(_tts_call(part, voice, role, speed))
            pcm += chunk
            for w, start, length in timings:
                words.append(w)
                wtimes.append(offset + start)
                wdurations.append(length)
    except httpx.HTTPError as exc:
        log.warning("Yandex TTS failed: %s", exc)
        raise VoiceError(502, "Сервис синтеза не ответил") from exc
    if not pcm:
        raise VoiceError(502, "Сервис синтеза вернул пустое аудио")
    return {
        "provider": "yandex", "voice": voice, "role": role, "mime": "audio/wav",
        "audio": base64.b64encode(wav_bytes(bytes(pcm), TTS_RATE)).decode(), "duration_ms": len(pcm) * 1000 // (2 * TTS_RATE),
        "words": words, "wtimes": wtimes, "wdurations": wdurations,
    }


# ---------- файлы ----------

GLB_MAGIC, GLB_JSON = b"glTF", 0x4E4F534A


def check_glb(data: bytes) -> dict:
    """Проверка GLB до сохранения: сигнатура, версия 2, длина из заголовка, JSON-чанк, узлы, которые требует TalkingHead."""
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise VoiceError(422, "Это не GLB: файл должен начинаться с сигнатуры glTF")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise VoiceError(422, f"Нужен glTF 2.0, а в файле версия {version}")
    if length != len(data):
        raise VoiceError(422, "GLB повреждён: длина не совпадает с заголовком")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != GLB_JSON or 20 + chunk_len > len(data):
        raise VoiceError(422, "GLB повреждён: нет JSON-описания сцены")
    try:
        doc = json.loads(data[20:20 + chunk_len])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VoiceError(422, "GLB повреждён: JSON-описание не читается") from exc
    nodes = {n.get("name") for n in doc.get("nodes", [])}
    missing = [n for n in ("Armature", "Head") if n not in nodes]
    if missing:
        raise VoiceError(422, f"В модели нет узлов {', '.join(missing)}: TalkingHead ждёт скелет в стиле Mixamo/Ready Player Me (см. README)")
    targets = {t for m in doc.get("meshes", []) for t in (m.get("extras") or {}).get("targetNames", [])}
    visemes = sorted(t for t in targets if t.startswith("viseme_"))
    warnings = []
    if not visemes:
        warnings.append("Нет визем Oculus (viseme_aa, viseme_PP …): губы двигаться не будут")
    if "eyeBlinkLeft" not in targets:
        warnings.append("Нет ARKit-блендшейпов (eyeBlinkLeft …): мимика настроения будет слабой")
    return {"morph_targets": len(targets), "visemes": len(visemes), "warnings": warnings}


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def save_avatar(data: bytes, filename: str) -> dict:
    if not filename.lower().endswith(".glb"):
        raise VoiceError(415, "Нужен файл .glb")
    if len(data) > settings.avatar_max_mb * 1024 * 1024:
        raise VoiceError(413, f"Модель больше {settings.avatar_max_mb} МБ: сожмите её (gltf-transform meshopt, текстуры webp 1024)")
    info = check_glb(data)
    folder = uploads_dir() / "avatars"
    if _dir_size(folder) + len(data) > settings.uploads_max_mb * 1024 * 1024:
        raise VoiceError(507, "Место под загрузки на сервере закончилось")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}.glb"
    (folder / name).write_bytes(data)
    return {"url": f"/uploads/avatars/{name}", "size": len(data), **info}


def save_voice(data: bytes, ext: str) -> str | None:
    """Исходная запись голосового для плеера в чате. Не сохранилась — ход всё равно идёт, просто без плеера."""
    folder = uploads_dir() / "voice"
    try:
        if ext not in ALLOWED_VOICE_EXT or _dir_size(folder) + len(data) > settings.uploads_max_mb * 1024 * 1024:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid4().hex}.{ext}"
        (folder / name).write_bytes(data)
        return f"/uploads/voice/{name}"
    except OSError as exc:
        log.warning("voice file not saved: %s", exc)
        return None
