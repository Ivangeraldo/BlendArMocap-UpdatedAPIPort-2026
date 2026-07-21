import time
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from .mp_detector_node import DetectorNode
from . import cv_stream, mp_models


class _HandResult:
    __slots__ = ("multi_hand_landmarks", "multi_hand_world_landmarks", "multi_handedness")

    def __init__(self, res):
        self.multi_hand_landmarks = res.hand_landmarks or []
        self.multi_hand_world_landmarks = res.hand_world_landmarks or []
        # Cada entrada es una lista de Category (normalmente 1); Category tiene
        # .category_name == "Left"/"Right", igual que el proto viejo pero más directo.
        self.multi_handedness = res.handedness or []


class _HandLandmarkerCompat:
    """Igual que en mp_pose_detector: envuelve HandLandmarker con .process(frame)
    y mantiene el landmarker cargado entre frames en vez de recrearlo cada vez.
    Usa RunningMode.VIDEO (no IMAGE) para continuidad de tracking entre frames
    y así reducir el jitter."""

    def __init__(self, model_complexity=1, min_detection_confidence=0.7):
        model_path = mp_models.get_model_path("hand_landmarker", model_complexity)
        base_options = mp_tasks.BaseOptions(model_asset_path=model_path)
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
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
        return _HandResult(res)

    def close(self):
        self._landmarker.close()


class HandDetector(DetectorNode):
    def __init__(self, stream, hand_model_complexity: int = 1, min_detection_confidence: float = .7):
        DetectorNode.__init__(self, stream)
        self.hand_model_complexity = hand_model_complexity
        self.min_detection_confidence = min_detection_confidence
        self._compat = None

    def update(self, data, frame):
        if self._compat is None:
            self._compat = _HandLandmarkerCompat(self.hand_model_complexity, self.min_detection_confidence)
        return self.exec_detection(self._compat), frame

    @staticmethod
    def separate_hands(hand_data):
        left_hand = [data[0] for data in hand_data if data[1][1] is False]
        right_hand = [data[0] for data in hand_data if data[1][1] is True]
        return left_hand, right_hand

    @staticmethod
    def cvt_hand_orientation(orientation):
        """orientation: multi_handedness (lista, una por mano detectada, de
        listas de Category). Category.category_name es 'Left' o 'Right'."""
        if not orientation:
            return None
        result = []
        for idx, categories in enumerate(orientation):
            is_right = bool(categories) and categories[0].category_name == "Right"
            result.append([idx, is_right])
        return result

    def empty_data(self):
        return [[], []]

    def detected_data(self, mp_res):
        data = [self.cvt2landmark_array(hand) for hand in mp_res.multi_hand_world_landmarks]
        left_hand_data, right_hand_data = self.separate_hands(
            list(zip(data, self.cvt_hand_orientation(mp_res.multi_handedness))))
        return [left_hand_data, right_hand_data]

    def contains_features(self, mp_res):
        if not mp_res.multi_hand_landmarks and not mp_res.multi_handedness:
            return False
        return True

    def draw_result(self, s, mp_res, mp_drawings):
        for hand in mp_res.multi_hand_landmarks:
            mp_models.draw_hand_landmarks(s.frame, hand)

    def __del__(self):
        if getattr(self, "_compat", None) is not None:
            self._compat.close()
        super().__del__()


if __name__ == '__main__':
    import logging
    from ...cgt_core.cgt_calculators_nodes import mp_calc_hand_rot
    from ...cgt_core.cgt_patterns import cgt_nodes
    logging.getLogger().setLevel(logging.DEBUG)

    chain = cgt_nodes.NodeChain()

    detector = HandDetector(cv_stream.Stream(0))
    calc = mp_calc_hand_rot.HandRotationCalculator()

    chain.append(detector)
    chain.append(calc)

    frame, data = 0, []
    for _ in range(50):
        frame += 1
        data, frame = chain.update(data, frame)
    del detector
# endregion
