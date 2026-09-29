"""Встроенные персонажи для 3D-режима: один список для формы сценария, генератора карточек и сидов."""
import hashlib

from pydantic import BaseModel


class Character(BaseModel):
    id: str
    name: str
    style: str  # chibi | pixar
    voice: str  # female | male
    url: str
    portrait: str
    ready: bool


CHARACTERS: list[Character] = [
    Character(id="b1", name="Ольга", style="chibi", voice="female", url="/avatars/chibi_b1.glb", portrait="/avatars/portraits/b1.webp", ready=True),
    Character(id="b2", name="Марина", style="chibi", voice="female", url="/avatars/chibi_b2.glb", portrait="/avatars/portraits/b2.webp", ready=True),
    Character(id="b3", name="Сергей", style="chibi", voice="male", url="/avatars/chibi_b3.glb", portrait="/avatars/portraits/b3.webp", ready=True),
    Character(id="b4", name="Артур", style="chibi", voice="male", url="/avatars/chibi_b4.glb", portrait="/avatars/portraits/b4.webp", ready=True),
    Character(id="a1", name="Ольга", style="pixar", voice="female", url="/avatars/pixar_a1.glb", portrait="/avatars/portraits/a1.webp", ready=True),
    Character(id="a2", name="Марина", style="pixar", voice="female", url="/avatars/pixar_a2.glb", portrait="/avatars/portraits/a2.webp", ready=False),
    Character(id="a3", name="Сергей", style="pixar", voice="male", url="/avatars/pixar_a3.glb", portrait="/avatars/portraits/a3.webp", ready=False),
    Character(id="a4", name="Артур", style="pixar", voice="male", url="/avatars/pixar_a4.glb", portrait="/avatars/portraits/a4.webp", ready=False),
]


def pick(voice: str, seed: str = "") -> str | None:
    """Готовый персонаж того же пола; выбор стабилен для одного и того же имени собеседника."""
    ready = [c for c in CHARACTERS if c.ready and c.voice == voice]
    if not ready:
        return None
    return ready[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(ready)].url
