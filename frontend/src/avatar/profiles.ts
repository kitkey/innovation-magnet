// Камера и доп. настроения под конкретные модели. Чиби: крупная голова и короткие ноги, кадр голова+плечи для сцены 4:5.
// Для MPFB и загруженных пользователем аватаров остаётся камера по умолчанию.
export type Camera = { cameraDistance: number; cameraY: number; cameraRotateY: number };

export const DEFAULT_CAMERA: Camera = { cameraDistance: -1, cameraY: -0.1, cameraRotateY: 0 };
const CHIBI_CAMERA: Camera = { cameraDistance: 4.5, cameraY: 0.8, cameraRotateY: 0 };

export const CHIBI_AVATARS = ["/avatars/chibi_b1.glb", "/avatars/chibi_b2.glb"];

export function cameraFor(url: string): Camera {
  return CHIBI_AVATARS.includes(url) ? CHIBI_CAMERA : DEFAULT_CAMERA;
}

// Скепсис: одна бровь вверх, другая вниз с прищуром, уголок рта вниз. Строится на базе neutral.
export const EXTRA_MOODS: Record<string, { base: string; baseline: Record<string, number> }> = {
  skeptic: {
    base: "neutral",
    baseline: {
      browOuterUpLeft: 1, browInnerUp: 0.45, browDownRight: 0.9, eyeSquintRight: 0.45, eyeWideLeft: 0.3,
      mouthFrownRight: 0.75, mouthPressRight: 0.45, mouthLeft: 0.15, mouthSmileLeft: 0.1,
    },
  },
};
