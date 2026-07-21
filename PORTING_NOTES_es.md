# PORTING_NOTES_es.md — Breakdown técnico del port a la MediaPipe Tasks API

*[Read this in English](PORTING_NOTES.md)*

Este documento detalla, archivo por archivo, qué se cambió y por qué. Pensado para
quien quiera revisar el port, contribuir, o portar futuras versiones de mediapipe.

## Contexto: por qué había que portar esto

BlendArMocap original (última versión pública) usa `mediapipe.solutions.pose`,
`mediapipe.solutions.hands`, `mediapipe.solutions.face_mesh` y
`mediapipe.solutions.holistic`. Este namespace (la "Solutions API") fue
deprecado por Google y ya no existe en `pip install mediapipe` actual —
`import mediapipe.solutions` falla con `AttributeError` en cualquier
instalación moderna. La sucesora oficial es la **Tasks API**
(`mediapipe.tasks.python.vision`), con clases separadas por tarea:
`PoseLandmarker`, `HandLandmarker`, `FaceLandmarker`. No existe un reemplazo
directo de "Holistic" (los tres modelos combinados en uno).

## Archivos modificados

### `src/cgt_mediapipe/cgt_mp_core/mp_pose_detector.py`
- Reemplaza `mp.solutions.pose.Pose()` por `vision.PoseLandmarker`.
- Clase `_PoseLandmarkerCompat` envuelve el landmarker para exponer
  `.process(frame_rgb) -> _PoseResult` con los mismos atributos
  (`.pose_landmarks`, `.pose_world_landmarks`) que el código original leía,
  para que el resto de la cadena de nodos (`cgt_core_chains.py`,
  `mp_pose_out.py`) no necesite cambios.
- El landmarker se crea **una sola vez** (no por frame) — recrearlo cada
  frame recargaría el modelo `.task` desde disco cada vez.
- `RunningMode.VIDEO` con timestamps monotónicos (`time.perf_counter()`),
  no `RunningMode.IMAGE`. Ver sección "Jitter" más abajo.

### `src/cgt_mediapipe/cgt_mp_core/mp_hand_detector.py`
Mismo patrón que pose, con `HandLandmarker`. La resolución de lateralidad
(`multi_handedness`) usa `res.handedness[i][0].category_name` ("Left"/"Right"),
equivalente al campo `.classification[0].label` del proto viejo.

### `src/cgt_mediapipe/cgt_mp_core/mp_face_detector.py`
`FaceLandmarker` con `output_face_blendshapes=True` y
`output_facial_transformation_matrixes=True`. La Tasks API no tiene un
parámetro equivalente a `refine_landmarks` de la API vieja — el modelo actual
ya incluye los 10 puntos de iris por defecto (478 landmarks totales); como
`mp_calc_face_rot.py` solo usa los primeros 468, esto es compatible sin cambios
en esa capa.

### `src/cgt_mediapipe/cgt_mp_core/mp_holistic_detector.py`
No existe modelo Holistic en la Tasks API. Esta clase corre los tres
landmarkers (Pose/Face/Hand) sobre el mismo frame, con el mismo reloj de
timestamps, y combina los resultados en un objeto `_HolisticResult` con la
misma forma que producía el `HolisticDetector` original.

### Jitter: `RunningMode.IMAGE` vs `RunningMode.VIDEO`
Causa raíz del temblor reportado en captura en vivo durante el desarrollo de
este port: los 4 detectores usaban inicialmente `RunningMode.IMAGE`, que
analiza cada frame de forma aislada sin ninguna continuidad temporal.
`RunningMode.VIDEO` (con `detect_for_video(mp_image, timestamp_ms)` y
timestamps crecientes) habilita el tracking interno de MediaPipe entre
frames, reduciendo notablemente el temblor. Es el cambio de mayor impacto
de todo el port.

### `src/cgt_mediapipe/cgt_dependencies.py`
No relacionado con la API de detección, pero crítico para estabilidad:

1. **Instalación de dependencias más simple y robusta.** `required_dependencies`
   ya no instala `opencv-python` como paquete separado — solo
   `mediapipe==0.10.33`, que declara `opencv-contrib-python` como su propia
   dependencia y la instala solo. Tener dos variantes de opencv instaladas a
   la vez corrompe el paquete `cv2` en Windows (comparten el mismo nombre de
   import, y `pip` no sabe que son mutuamente excluyentes), causando el error
   *"module 'cv2' has no attribute 'VideoCapture'"* incluso en instalaciones
   nuevas. La versión de mediapipe queda fijada, no "la última", para que la
   instalación sea reproducible.

2. **Blindaje del bloque de nivel de módulo.** Este archivo tiene código que
   corre **al importar el módulo** (durante `addon_enable`), usando
   `importlib.metadata` para chequear versiones/rutas de paquetes instalados.
   Si la metadata de un paquete estaba incompleta (típico tras reinstalaciones
   manuales previas), `Path(location) / dependency.pkg` podía recibir
   `location=None` y lanzar `TypeError`, tumbando el registro de **todo el
   addon** con un `RuntimeError` genérico sin traceback útil. Ahora:
   - `get_package_info()` retorna `(version, None)` si `location` es `None`.
   - `uninstall_dependency()` tiene el mismo guard.
   - El bloque completo de nivel de módulo (chequeo de site-packages, binario
     de Python, info de cada dependencia) está envuelto en `try/except`
     individuales con valores de respaldo seguros.

### `requirements.txt`
Refleja el mismo cambio: `mediapipe==0.10.33` únicamente, sin `opencv-python`
por separado.

### `src/cgt_transfer/data/Generic_MetaRig_Basic.json` (nuevo)
El config original (`Rigify_Humanoid_DefaultFace_v0.6.1.json`) fue diseñado
para animar un rig **ya generado** por Rigify — sus targets son huesos de
control como `hand_ik.L`, `forearm_tweak.L`, `upper_arm_fk.L`, que solo
existen después de correr "Generate Rig". Si se usa ese config sobre el
metarig crudo, `tf_get_object_properties.get_target()` aborta en silencio
para cada landmark (el hueso buscado no existe → `return None, None, 'ABORT'`),
sin ningún error visible ni log — simplemente no se crea ningún constraint en
el rig, aunque los empties (drivers) sí reciban su constraint de plantilla.

`Generic_MetaRig_Basic.json` reutiliza el mismo mecanismo `driver_type: REMAP`
del original (que crea un driver 1:1 sobre una propiedad del landmark), pero:
- Apunta a huesos crudos de metarig (`upper_arm.L`, `forearm.L`, `thigh.L`,
  `shin.L`, `head`, `spine.003`).
- Usa constraint `DAMPED_TRACK` en vez de `COPY_LOCATION`/`COPY_ROTATION`,
  con remap de posición (loc_x/y/z) en vez de rotación — cada hueso apunta
  hacia la posición de la siguiente articulación de la cadena.
- Cubre 10 landmarks (brazos, piernas, cabeza, torso). No incluye manos ni
  cara todavía.

## Qué NO se tocó (y por qué no hizo falta)

- `cgt_core_chains.py`, los nodos de salida (`mp_pose_out.py`,
  `mp_hand_out.py`, `mp_face_out.py`) y todo el sistema de colecciones
  `cgt_POSE`/`cgt_HANDS`/`cgt_FACE`/`cgt_DRIVERS`: siguen esperando la misma
  forma de datos (arrays de landmarks con `.x/.y/.z`), que las clases
  `*Compat` siguen produciendo sin cambios.
- El sistema completo de transferencia (`cgt_tf_operators.py`,
  `tf_transfer_management.py`, `tf_load_object_properties.py`,
  `tf_get_object_properties.py`, `tf_set_object_properties.py`): la lógica de
  drivers, remapeo y cadenas IK es independiente de qué API de detección se
  use, así que no requirió ningún cambio.

## Ideas para seguir

- Cubrir manos y cara en `Generic_MetaRig_Basic.json`.
- Calcular orientación real de mano/cabeza con geometría (3 puntos → base
  ortonormal, o la matriz de transformación facial que da `FaceLandmarker`)
  en vez de solo posición + Damped Track, para reducir el "roll" incorrecto
  en muñecas.
- Probar y documentar compatibilidad en macOS/Linux.
- Benchmark de jitter antes/después de `RunningMode.VIDEO` con números reales.
