# BlendArMocap NX

**Fork / port de [BlendArMocap](https://github.com/cgtinker/BlendArMocap) (por [cgtinker](https://github.com/cgtinker)) actualizado para funcionar con la MediaPipe Tasks API moderna, en Blender 4.2+ (probado en 4.5 LTS).**

BlendArMocap original dejó de funcionar en instalaciones nuevas de Blender/Python porque dependía de `mediapipe.solutions` (Pose, Hands, Face Mesh, Holistic), una API que Google deprecó y removió de las versiones actuales de `mediapipe`. Este fork reemplaza esa capa de detección por la **Tasks API** (`PoseLandmarker`, `HandLandmarker`, `FaceLandmarker`) manteniendo intacta toda la arquitectura original: el sistema de nodos de captura, la colección de empties `cgt_*`, y el sistema de transferencia de animación a un rig vía archivos de configuración JSON.

> El diseño original, el sistema de retargeting y la gran mayoría del código base son de **cgtinker**. Este repositorio existe para mantener el addon funcionando en Blender/Python/MediaPipe actuales — no para reclamar autoría. Licencia GPLv3, igual que el original (ver `LICENSE`). El repo original está marcado como *discontinued* por su autor; este fork nace de esa nota.

---

## Qué cambia respecto al original

### 1. Detección: `mediapipe.solutions` → Tasks API
Los 4 detectores (`mp_pose_detector.py`, `mp_hand_detector.py`, `mp_face_detector.py`, `mp_holistic_detector.py`) fueron reescritos sobre `PoseLandmarker`, `HandLandmarker` y `FaceLandmarker` de `mediapipe.tasks.python.vision`, con clases `*Compat` que exponen la misma interfaz `.process(frame)` que el código original esperaba — el resto de la cadena de nodos no necesitó cambios.

- **`RunningMode.VIDEO`, no `IMAGE`.** La Tasks API ofrece modo `IMAGE` (cada frame aislado, sin memoria del anterior) y `VIDEO` (timestamps crecientes, continuidad de tracking entre frames). Usar `IMAGE` en captura en vivo produce temblor notable; este port usa `VIDEO` con un contador de timestamps monotónico por landmarker.
- **No existe un modelo "Holistic" único en la Tasks API.** `mp_holistic_detector.py` corre Pose + Face + Hand por separado sobre el mismo frame y combina los resultados con la misma forma que producía el `HolisticDetector` original.
- Los modelos `.task` se descargan automáticamente la primera vez que se necesitan (bucket público de Google) — a diferencia de la API vieja, que los traía embebidos.

### 2. Instalación de dependencias, más resiliente
- `mediapipe` fijado a `0.10.33` (versión probada, no "la última disponible") — evita que cada reinstalación traiga una cadena de dependencias distinta.
- **Ya no se instala `opencv-python` por separado.** `mediapipe` trae `opencv-contrib-python` como dependencia propia; instalar además otra variante de opencv corrompía el paquete `cv2` en Windows (ambas comparten el mismo nombre de import y pip no sabe que son mutuamente excluyentes) — este era el origen del error *"module 'cv2' has no attribute 'VideoCapture'"* incluso en instalaciones nuevas.
- El bloque de `cgt_dependencies.py` que verifica versiones instaladas corre **al importar el módulo** (o sea, al activar el addon). Antes, si la metadata de un paquete estaba incompleta (típico tras reinstalaciones manuales previas), una excepción ahí tumbaba el registro de **todo el addon** con un `RuntimeError` genérico. Ahora cada paso está blindado con try/except y valores de respaldo seguros.

### 3. Nuevo Transfer Type: `Generic_MetaRig_Basic`
El único config que traía el addon original (`Rigify_Humanoid_DefaultFace_v0.6.1.json`) apunta a huesos de control que **solo existen en un rig ya generado por Rigify** (`hand_ik.L`, `forearm_tweak.L`, `upper_arm_fk.L`, etc.). Usarlo sobre el metarig sin generar aborta en silencio hueso por hueso — sin ningún error visible, simplemente no se crea ningún constraint.

`Generic_MetaRig_Basic.json` es una alternativa pensada para animar directo un metarig sin generar (huesos `upper_arm.L`, `forearm.L`, `thigh.L`, `shin.L`, `head`...). Usa el mismo mecanismo de drivers del original pero con constraints `Damped Track` en vez de `Copy Location`/`Copy Rotation` sobre huesos IK: cada hueso apunta hacia la siguiente articulación de la cadena. Cubre brazos, piernas, cabeza y una aproximación simple de torso (10 landmarks; no incluye dedos ni cara todavía — ver *Limitaciones*).

---

## Instalación

1. `Preferences > Add-ons > Install from Disk` → selecciona el `.zip` de este repo.
2. Activa el addon. Ve a la pestaña de dependencias (dentro de las preferencias del addon) y dale a **Install dependencies** — instala `mediapipe==0.10.33` (que a su vez trae `opencv-contrib-python` y `numpy`) con `pip --user`, sin requerir permisos de administrador.
3. Si algo quedó instalado a medias por una corrida anterior de una versión previa del addon, usa el botón de reparación disponible en el mismo panel.

Requiere Blender 4.2 o superior (probado en 4.5 LTS). Python 3.11+ (el que trae Blender).

---

## Uso rápido

1. **3D View > Tool > BlendArMocap > MediaPipe**: elige Webcam o Video, tipo de detección (Pose/Hands/Face), dale a *Start Detection*.
2. Esto crea una jerarquía de empties `cgt_*` bajo la colección `cgt_DRIVERS`.
3. **Transfer**: elige tu Armature destino, la colección de Drivers (`cgt_POSE` / `cgt_HANDS` / `cgt_FACE`), y el Transfer Type:
   - `Rigify_Humanoid_DefaultFace_v0.6.1` → para un rig **ya generado** por Rigify (botón *Generate Rig*).
   - `Generic_MetaRig_Basic` → para el metarig crudo (sin generar) o un rig con nomenclatura de huesos similar.
4. **Load** → **Transfer Animation**.

---

## Limitaciones conocidas / trabajo pendiente

- `Generic_MetaRig_Basic` no cubre manos ni cara todavía, solo torso/brazos/piernas/cabeza — es nuevo en este release y agradecemos reportes de uso.
- El jitter mejoró notablemente con `RunningMode.VIDEO`, pero no hay un benchmark formal contra la implementación original.
- Desarrollo y pruebas hechos principalmente en Windows 11 + Blender 4.5 LTS. Falta reportar compatibilidad en macOS/Linux.

## Créditos

- Autor y diseño original: [cgtinker](https://github.com/cgtinker) — [BlendArMocap](https://github.com/cgtinker/BlendArMocap).
- Port a la Tasks API moderna y fixes de estabilidad: este fork.
- Licencia: GPLv3 (heredada del proyecto original, ver `LICENSE`).

Ver `PORTING_NOTES.md` para el detalle técnico archivo por archivo.
