import time
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from . import cv_stream, mp_detector_node, mp_models


class _PoseResult:
    """Adapta el resultado de PoseLandmarker (Tasks API) a los nombres de
    atributo que usaba el resultado de solutions.Pose(): .pose_landmarks y
    .pose_world_landmarks, pero ahora como listas planas (sin .landmark),
    tomando la primera persona detectada (el addon original solo maneja una)."""
    __slots__ = ("pose_landmarks", "pose_world_landmarks")

    def __init__(self, res):
        self.pose_landmarks = res.pose_landmarks[0] if res.pose_landmarks else None
        self.pose_world_landmarks = res.pose_world_landmarks[0] if res.pose_world_landmarks else None


class _PoseLandmarkerCompat:
    """Envuelve PoseLandmarker para exponer .process(frame) como la vieja
    solutions.Pose(). A diferencia del addon original (que recreaba
    solutions.Pose() en cada frame, algo barato con la API vieja), aquí el
    landmarker se crea UNA sola vez y se reutiliza — recrear un PoseLandmarker
    de la Tasks API en cada frame implicaría recargar el modelo .task del
    disco cada vez, lo cual sí sería muy lento.

    IMPORTANTE (jitter): se usa RunningMode.VIDEO en vez de IMAGE. En modo
    IMAGE cada frame se analiza aislado, sin memoria del anterior, lo que
    produce temblor notable en tiempo real. VIDEO usa los timestamps para
    mantener continuidad de tracking entre frames (igual que hacía por dentro
    la vieja solutions.Pose() en modo streaming)."""

    def __init__(self, model_complexity=1, min_detection_confidence=0.7):
        model_path = mp_models.get_model_path("pose_landmarker", model_complexity)
        base_options = mp_tasks.BaseOptions(model_asset_path=model_path)
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        self._landmarker = mp_vision.PoseLandmarker.create_from_options(options)
        self._t0 = time.perf_counter()
        self._last_ts = -1

    def _next_timestamp_ms(self):
        ts = int((time.perf_counter() - self._t0) * 1000)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts
        return ts

    def process(self, frame_rgb):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        res = self._landmarker.detect_for_video(mp_image, self._next_timestamp_ms())
        return _PoseResult(res)

    def close(self):
        self._landmarker.close()


class PoseDetector(mp_detector_node.DetectorNode):
    def __init__(self, stream, pose_model_complexity: int = 1, min_detection_confidence: float = 0.7):
        mp_detector_node.DetectorNode.__init__(self, stream)
        self.pose_model_complexity = pose_model_complexity
        self.min_detection_confidence = min_detection_confidence
        self._compat = None

    # Antes: "with self.solution.Pose(...) as mp_lib: return self.exec_detection(mp_lib), frame"
    # Ahora el landmarker persiste entre llamadas (ver _PoseLandmarkerCompat).
    def update(self, data, frame):
        if self._compat is None:
            self._compat = _PoseLandmarkerCompat(self.pose_model_complexity, self.min_detection_confidence)
        return self.exec_detection(self._compat), frame

    def detected_data(self, mp_res):
        return self.cvt2landmark_array(mp_res.pose_world_landmarks)

    def empty_data(self):
        return []

    def contains_features(self, mp_res):
        if not mp_res.pose_world_landmarks:
            return False
        return True

    def draw_result(self, s, mp_res, mp_drawings):
        mp_models.draw_pose_landmarks(s.frame, mp_res.pose_landmarks)

    def __del__(self):
        if getattr(self, "_compat", None) is not None:
            self._compat.close()
        super().__del__()


# region manual tests
if __name__ == '__main__':
    from . import cv_stream
    from ...cgt_core.cgt_calculators_nodes import mp_calc_pose_rot
    detector = PoseDetector(cv_stream.Stream(0))
    calc = mp_calc_pose_rot.PoseRotationCalculator()
    frame = 0
    for _ in range(50):
        frame += 1
        data, frame = detector.update(None, frame)
        data, frame = calc.update(data, frame)
        print(data)

    del detector
# endregion
