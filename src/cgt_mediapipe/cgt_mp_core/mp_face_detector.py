import time
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from .mp_detector_node import DetectorNode
from . import mp_models


class _FaceResult:
    __slots__ = ("multi_face_landmarks",)

    def __init__(self, res):
        self.multi_face_landmarks = res.face_landmarks or []


class _FaceLandmarkerCompat:
    def __init__(self, min_detection_confidence=0.7):
        model_path = mp_models.get_model_path("face_landmarker", 1)
        base_options = mp_tasks.BaseOptions(model_asset_path=model_path)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
            # El modelo de la Tasks API ya incluye los 10 puntos de iris (478
            # landmarks totales) por defecto — no hay toggle equivalente a
            # `refine_landmarks` de la API vieja. mp_calc_face_rot.py solo usa
            # los primeros 468, así que esto es compatible de cualquier forma.
        )
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)
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
        return _FaceResult(res)

    def close(self):
        self._landmarker.close()


class FaceDetector(DetectorNode):
    def __init__(self, stream, refine_face_landmarks: bool = False, min_detection_confidence: float = 0.7):
        DetectorNode.__init__(self, stream)
        self.refine_face_landmarks = refine_face_landmarks
        self.min_detection_confidence = min_detection_confidence
        self._compat = None

    def update(self, data, frame):
        if self._compat is None:
            self._compat = _FaceLandmarkerCompat(self.min_detection_confidence)
        return self.exec_detection(self._compat), frame

    def empty_data(self):
        return [[[]]]

    def detected_data(self, mp_res):
        return [self.cvt2landmark_array(landmark) for landmark in mp_res.multi_face_landmarks]

    def contains_features(self, mp_res):
        if not mp_res.multi_face_landmarks:
            return False
        return True

    def draw_result(self, s, mp_res, mp_drawings):
        for face_landmarks in mp_res.multi_face_landmarks:
            mp_models.draw_face_landmarks(s.frame, face_landmarks)

    def __del__(self):
        if getattr(self, "_compat", None) is not None:
            self._compat.close()
        super().__del__()


# region manual tests
if __name__ == '__main__':
    from . import cv_stream
    from ...cgt_core.cgt_calculators_nodes import mp_calc_face_rot
    detector = FaceDetector(cv_stream.Stream(0))
    calc = mp_calc_face_rot.FaceRotationCalculator()
    frame = 0
    for _ in range(50):
        frame += 1
        data, frame = detector.update(None, frame)
        data, frame = calc.update(data, frame)

    del detector
# endregion
