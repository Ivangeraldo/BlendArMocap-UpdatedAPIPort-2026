import time
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from . import cv_stream, mp_detector_node, mp_models


class _HolisticResult:
    __slots__ = ("pose_landmarks", "face_landmarks", "left_hand_landmarks", "right_hand_landmarks")

    def __init__(self, pose_landmarks, face_landmarks, left_hand_landmarks, right_hand_landmarks):
        self.pose_landmarks = pose_landmarks
        self.face_landmarks = face_landmarks
        self.left_hand_landmarks = left_hand_landmarks
        self.right_hand_landmarks = right_hand_landmarks


class _HolisticLandmarkerCompat:
    """La Tasks API moderna NO trae un modelo 'Holistic' único como la API
    vieja (mediapipe.solutions.holistic) — Google lo descontinuó ahí también.
    Para mantener el mismo comportamiento (pose + cara + ambas manos en un
    solo detector), corremos aquí los tres landmarkers (Pose/Face/Hand) sobre
    el mismo frame y combinamos los resultados con la misma forma que producía
    HolisticDetector original.

    Los tres landmarkers usan RunningMode.VIDEO con el MISMO reloj de
    timestamps (self._t0/_last_ts compartido) para mantener continuidad de
    tracking entre frames y evitar el jitter que da el modo IMAGE."""

    def __init__(self, model_complexity=1, min_detection_confidence=.7, refine_face_landmarks=False):
        pose_opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(
                model_asset_path=mp_models.get_model_path("pose_landmarker", model_complexity)),
            running_mode=mp_vision.RunningMode.VIDEO,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        face_opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(
                model_asset_path=mp_models.get_model_path("face_landmarker", 1)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        hand_opts = mp_vision.HandLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(
                model_asset_path=mp_models.get_model_path("hand_landmarker", model_complexity)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        self._pose = mp_vision.PoseLandmarker.create_from_options(pose_opts)
        self._face = mp_vision.FaceLandmarker.create_from_options(face_opts)
        self._hand = mp_vision.HandLandmarker.create_from_options(hand_opts)
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
        ts = self._next_timestamp_ms()

        pose_res = self._pose.detect_for_video(mp_image, ts)
        face_res = self._face.detect_for_video(mp_image, ts)
        hand_res = self._hand.detect_for_video(mp_image, ts)

        pose_landmarks = pose_res.pose_landmarks[0] if pose_res.pose_landmarks else None
        face_landmarks = face_res.face_landmarks[0] if face_res.face_landmarks else None

        left_hand_landmarks = None
        right_hand_landmarks = None
        for landmarks, handedness in zip(hand_res.hand_landmarks or [], hand_res.handedness or []):
            if not handedness:
                continue
            if handedness[0].category_name == "Left":
                left_hand_landmarks = landmarks
            elif handedness[0].category_name == "Right":
                right_hand_landmarks = landmarks

        return _HolisticResult(pose_landmarks, face_landmarks, left_hand_landmarks, right_hand_landmarks)

    def close(self):
        self._pose.close()
        self._face.close()
        self._hand.close()


class HolisticDetector(mp_detector_node.DetectorNode):
    def __init__(self, stream, model_complexity: int = 1,
                 min_detection_confidence: float = .7, refine_face_landmarks: bool = False):
        mp_detector_node.DetectorNode.__init__(self, stream)
        self.model_complexity = model_complexity
        self.min_detection_confidence = min_detection_confidence
        self.refine_face_landmarks = refine_face_landmarks
        self._compat = None

    def update(self, data, frame):
        if self._compat is None:
            self._compat = _HolisticLandmarkerCompat(
                self.model_complexity, self.min_detection_confidence, self.refine_face_landmarks)
        return self.exec_detection(self._compat), frame

    def empty_data(self):
        return [[[], []], [[[]]], []]

    def detected_data(self, mp_res):
        face, pose, l_hand, r_hand = [], [], [], []
        if mp_res.pose_landmarks:
            pose = self.cvt2landmark_array(mp_res.pose_landmarks)
        if mp_res.face_landmarks:
            face = self.cvt2landmark_array(mp_res.face_landmarks)
        if mp_res.left_hand_landmarks:
            l_hand = [self.cvt2landmark_array(mp_res.left_hand_landmarks)]
        if mp_res.right_hand_landmarks:
            r_hand = [self.cvt2landmark_array(mp_res.right_hand_landmarks)]
        # TODO: recheck every update, mp hands are flipped while detecting holistic.
        return [[r_hand, l_hand], [face], pose]

    def contains_features(self, mp_res):
        if not mp_res.pose_landmarks:
            return False
        return True

    def draw_result(self, s, mp_res, mp_drawings):
        if mp_res.face_landmarks:
            mp_models.draw_face_landmarks(s.frame, mp_res.face_landmarks)
        if mp_res.pose_landmarks:
            mp_models.draw_pose_landmarks(s.frame, mp_res.pose_landmarks)
        if mp_res.left_hand_landmarks:
            mp_models.draw_hand_landmarks(s.frame, mp_res.left_hand_landmarks)
        if mp_res.right_hand_landmarks:
            mp_models.draw_hand_landmarks(s.frame, mp_res.right_hand_landmarks)

    def __del__(self):
        if getattr(self, "_compat", None) is not None:
            self._compat.close()
        super().__del__()


# region manual tests
if __name__ == '__main__':
    detector = HolisticDetector(cv_stream.Stream(0))

    frame = 0
    for _ in range(15):
        frame += 1
        detector.update(None, frame)

    del detector
# endregion
