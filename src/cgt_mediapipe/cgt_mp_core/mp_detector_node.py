from __future__ import annotations

from abc import abstractmethod

from . import cv_stream
from ...cgt_core.cgt_patterns import cgt_nodes


class DetectorNode(cgt_nodes.InputNode):
    """Clase base de los detectores. Idéntica en espíritu a la del addon original:
    solo se le quitó la dependencia de `mediapipe.solutions.drawing_utils`
    (eliminado en mediapipe moderno) — el dibujo ahora lo hace cada subclase
    con las funciones de mp_models.py."""

    stream: cv_stream.Stream = None
    solution = None

    def __init__(self, stream: cv_stream.Stream = None):
        self.stream = stream

    @abstractmethod
    def update(self, *args):
        pass

    @abstractmethod
    def contains_features(self, mp_res):
        pass

    @abstractmethod
    def draw_result(self, s, mp_res, mp_drawings):
        pass

    @abstractmethod
    def empty_data(self):
        pass

    @abstractmethod
    def detected_data(self, mp_res):
        pass

    def exec_detection(self, mp_lib):
        """ Runs mediapipe detection on frame:
            -> detected_data: Detection Results.
            -> empty_data: No features detected.
            -> None: EOF or Finish.

        mp_lib: cualquier objeto con un método .process(frame_rgb) -> resultado.
        Cada detector concreto envuelve su landmarker de la Tasks API en un
        pequeño adaptador con esa misma firma .process(), para no tener que
        tocar esta función (igual que en el addon original, que recibía aquí
        una instancia de solutions.Pose()/Hands()/etc. con .process()). """
        self.stream.update()
        updated = self.stream.updated

        if not updated and self.stream.input_type == 0:
            # ignore if an update fails while stream detection
            return self.empty_data()

        elif not updated and self.stream.input_type == 1:
            # stop detection if update fails while movie detection
            return None

        if self.stream.frame is None:
            # ignore frame if not available
            return self.empty_data()

        # detect features in frame
        self.stream.frame.flags.writeable = False
        self.stream.set_color_space('rgb')
        mp_res = mp_lib.process(self.stream.frame)
        self.stream.set_color_space('bgr')

        # proceed if contains features
        if not self.contains_features(mp_res):
            self.stream.draw()
            if self.stream.exit_stream():
                return None
            return self.empty_data()

        # draw results
        self.draw_result(self.stream, mp_res, None)
        self.stream.draw()

        # exit stream
        if self.stream.exit_stream():
            return None

        return self.detected_data(mp_res)

    def cvt2landmark_array(self, landmark_list):
        """landmark_list: acepta tanto el objeto legacy con atributo `.landmark`
        (protobuf RepeatedField, API vieja) como una lista plana de landmarks
        de la Tasks API moderna — así detected_data() de cada subclase no
        necesita cambiar su forma de llamar a esta función."""
        if landmark_list is None:
            return []
        items = landmark_list.landmark if hasattr(landmark_list, "landmark") else landmark_list
        return [[idx, [landmark.x, landmark.y, landmark.z]] for idx, landmark in enumerate(items)]

    def __del__(self):
        if self.stream is not None:
            del self.stream
