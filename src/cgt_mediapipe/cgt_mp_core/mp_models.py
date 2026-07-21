"""
Manejo de los modelos .task de la MediaPipe Tasks API.

La API vieja (mediapipe.solutions.*) traía los modelos empacados dentro del
propio paquete pip. La Tasks API moderna (PoseLandmarker/HandLandmarker/
FaceLandmarker) NO los trae: hay que descargarlos una vez (son archivos .task
de unos pocos MB) y apuntar la API a un path local. Este módulo:

  - resuelve dónde guardar los modelos dentro del propio addon,
  - los descarga la primera vez que hacen falta (con caché en disco),
  - expone un par de funciones de dibujo simples con cv2 para reemplazar a
    `mediapipe.solutions.drawing_utils`, que ya no existe en mediapipe moderno.
"""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# URLs oficiales de Google para los modelos .task (float16, livianos).
# "lite"/"full"/"heavy" existen para pose; hand y face solo tienen una variante pública.
_MODEL_URLS = {
    ("pose_landmarker", 0): "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    ("pose_landmarker", 1): "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    ("pose_landmarker", 2): "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
    ("hand_landmarker", 0): "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    ("hand_landmarker", 1): "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    ("hand_landmarker", 2): "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    ("face_landmarker", 0): "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    ("face_landmarker", 1): "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    ("face_landmarker", 2): "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}


def get_model_path(kind: str, complexity: int = 1) -> str:
    """Devuelve el path local al modelo .task, descargándolo si hace falta.
    kind: 'pose_landmarker' | 'hand_landmarker' | 'face_landmarker'
    complexity: 0=lite/rápido, 1=full, 2=heavy/preciso (BlendArMocap ya exponía
    este mismo 0/1/2 como 'model_complexity' en sus operadores de detección)."""
    complexity = max(0, min(2, int(complexity)))
    url = _MODEL_URLS[(kind, complexity)]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    dest = MODELS_DIR / filename

    if not dest.exists() or dest.stat().st_size == 0:
        logging.info(f"Descargando modelo MediaPipe: {url} -> {dest}")
        tmp = dest.with_suffix(".part")
        try:
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(dest)
        except Exception as e:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"No se pudo descargar el modelo '{filename}' ({url}). "
                f"Revisa tu conexión a internet. Error original: {e}"
            )
    return str(dest)


# region dibujo manual (reemplaza a solutions.drawing_utils, eliminado en mediapipe moderno)
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (27, 31),
    (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


def _draw_connections(frame: np.ndarray, landmarks, connections, color, radius=3, thickness=2):
    if not landmarks:
        return
    h, w = frame.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
    for a, b in connections:
        if a < len(pts) and b < len(pts):
            cv2.line(frame, pts[a], pts[b], color, thickness)
    for x, y in pts:
        cv2.circle(frame, (x, y), radius, color, -1)


def draw_pose_landmarks(frame: np.ndarray, landmarks):
    _draw_connections(frame, landmarks, POSE_CONNECTIONS, (80, 220, 80), radius=4, thickness=2)


def draw_hand_landmarks(frame: np.ndarray, landmarks):
    _draw_connections(frame, landmarks, HAND_CONNECTIONS, (80, 180, 255), radius=3, thickness=2)


def draw_face_landmarks(frame: np.ndarray, landmarks):
    if not landmarks:
        return
    h, w = frame.shape[:2]
    for lm in landmarks[::2]:  # cada 2 puntos, el mesh completo (478) es muy denso
        cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 1, (200, 200, 200), -1)
# endregion
