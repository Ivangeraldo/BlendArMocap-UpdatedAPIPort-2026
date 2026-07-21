# PORTING_NOTES.md — Technical breakdown of the port to the MediaPipe Tasks API

*[Leer esto en español](PORTING_NOTES_es.md)*

This document details, file by file, what changed and why. Meant for anyone
reviewing the port, contributing, or porting future mediapipe versions.

## Context: why this needed porting

The original BlendArMocap (latest public release) uses `mediapipe.solutions.pose`,
`mediapipe.solutions.hands`, `mediapipe.solutions.face_mesh` and
`mediapipe.solutions.holistic`. That namespace (the "Solutions API") was
deprecated by Google and no longer exists in current `pip install mediapipe`
releases — `import mediapipe.solutions` fails with `AttributeError` on any
modern install. The official successor is the **Tasks API**
(`mediapipe.tasks.python.vision`), with separate classes per task:
`PoseLandmarker`, `HandLandmarker`, `FaceLandmarker`. There's no direct
replacement for "Holistic" (the three models combined into one).

## Modified files

### `src/cgt_mediapipe/cgt_mp_core/mp_pose_detector.py`
- Replaces `mp.solutions.pose.Pose()` with `vision.PoseLandmarker`.
- `_PoseLandmarkerCompat` wraps the landmarker to expose
  `.process(frame_rgb) -> _PoseResult` with the same attributes
  (`.pose_landmarks`, `.pose_world_landmarks`) the original code read, so the
  rest of the node chain (`cgt_core_chains.py`, `mp_pose_out.py`) needed no
  changes.
- The landmarker is created **once**, not per frame — recreating a Tasks API
  landmarker every frame would reload the `.task` model from disk each time.
- `RunningMode.VIDEO` with monotonic timestamps (`time.perf_counter()`), not
  `RunningMode.IMAGE`. See the "Jitter" section below.

### `src/cgt_mediapipe/cgt_mp_core/mp_hand_detector.py`
Same pattern as pose, with `HandLandmarker`. Handedness resolution
(`multi_handedness`) uses `res.handedness[i][0].category_name` ("Left"/"Right"),
equivalent to the old proto's `.classification[0].label` field.

### `src/cgt_mediapipe/cgt_mp_core/mp_face_detector.py`
`FaceLandmarker` with `output_face_blendshapes=True` and
`output_facial_transformation_matrixes=True`. The Tasks API has no parameter
equivalent to the old API's `refine_landmarks` — the current model already
includes the 10 iris points by default (478 landmarks total); since
`mp_calc_face_rot.py` only uses the first 468, this stays compatible without
changes on that layer.

### `src/cgt_mediapipe/cgt_mp_core/mp_holistic_detector.py`
There's no Holistic model in the Tasks API. This class runs the three
landmarkers (Pose/Face/Hand) on the same frame, sharing the same timestamp
clock, and combines the results into a `_HolisticResult` object shaped the
same way the original `HolisticDetector` was.

### Jitter: `RunningMode.IMAGE` vs `RunningMode.VIDEO`
Root cause of the jitter reported during live capture while developing this
port: the 4 detectors initially used `RunningMode.IMAGE`, which analyzes
each frame in isolation with no temporal continuity at all.
`RunningMode.VIDEO` (with `detect_for_video(mp_image, timestamp_ms)` and
increasing timestamps) enables MediaPipe's internal tracking between frames,
noticeably reducing jitter. This is the highest-impact change in the whole
port.

### `src/cgt_mediapipe/cgt_dependencies.py`
Not related to the detection API, but critical for stability:

1. **Simpler, more robust dependency install.** `required_dependencies` no
   longer installs `opencv-python` as a separate package — only
   `mediapipe==0.10.33`, which declares `opencv-contrib-python` as its own
   dependency and installs it on its own. Having two opencv variants
   installed at once corrupts the `cv2` package on Windows (they share the
   same import name, and `pip` has no idea they're mutually exclusive),
   causing the *"module 'cv2' has no attribute 'VideoCapture'"* error even on
   fresh installs. The mediapipe version is pinned, not "latest", so the
   install is reproducible.

2. **Module-level block hardening.** This file has code that runs **at
   import time** (during `addon_enable`), using `importlib.metadata` to
   check versions/paths of installed packages. If a package's metadata was
   incomplete (common after previous manual reinstalls),
   `Path(location) / dependency.pkg` could receive `location=None` and raise
   `TypeError`, taking down registration of **the entire addon** with a
   generic `RuntimeError` and no useful traceback. Now:
   - `get_package_info()` returns `(version, None)` if `location` is `None`.
   - `uninstall_dependency()` has the same guard.
   - The whole module-level block (site-packages check, Python binary,
     per-dependency info) is wrapped in individual `try/except` blocks with
     safe fallback values.

### `requirements.txt`
Reflects the same change: `mediapipe==0.10.33` only, no separate
`opencv-python`.

### `src/cgt_transfer/data/Generic_MetaRig_Basic.json` (new)
The original config (`Rigify_Humanoid_DefaultFace_v0.6.1.json`) was designed
to animate an **already-generated** Rigify rig — its targets are control
bones like `hand_ik.L`, `forearm_tweak.L`, `upper_arm_fk.L`, which only exist
after running "Generate Rig". Using that config on the raw metarig makes
`tf_get_object_properties.get_target()` silently abort for every landmark
(the target bone doesn't exist → `return None, None, 'ABORT'`), with no
visible error and no log — no constraint ever gets created on the rig, even
though the empties (drivers) do receive their template constraint.

`Generic_MetaRig_Basic.json` reuses the original's `driver_type: REMAP`
mechanism (which creates a 1:1 driver on a landmark property), but:
- Targets raw metarig bones (`upper_arm.L`, `forearm.L`, `thigh.L`,
  `shin.L`, `head`, `spine.003`).
- Uses a `DAMPED_TRACK` constraint instead of `COPY_LOCATION`/`COPY_ROTATION`,
  with position remap (loc_x/y/z) instead of rotation — each bone points
  toward the position of the next joint in the chain.
- Covers 10 landmarks (arms, legs, head, torso). Hands and face aren't
  included yet.

## What was NOT touched (and why it didn't need to be)

- `cgt_core_chains.py`, the output nodes (`mp_pose_out.py`, `mp_hand_out.py`,
  `mp_face_out.py`) and the whole collection system
  (`cgt_POSE`/`cgt_HANDS`/`cgt_FACE`/`cgt_DRIVERS`): they still expect the
  same data shape (landmark arrays with `.x/.y/.z`), which the `*Compat`
  classes keep producing unchanged.
- The entire transfer system (`cgt_tf_operators.py`,
  `tf_transfer_management.py`, `tf_load_object_properties.py`,
  `tf_get_object_properties.py`, `tf_set_object_properties.py`): the driver,
  remapping and IK chain logic is independent of which detection API is
  used, so it required no changes.

## Ideas going forward

- Cover hands and face in `Generic_MetaRig_Basic.json`.
- Compute real hand/head orientation from geometry (3 points → orthonormal
  basis, or the transformation matrix `FaceLandmarker` provides) instead of
  just position + Damped Track, to reduce incorrect wrist "roll".
- Test and document macOS/Linux compatibility.
- Formal jitter benchmark before/after `RunningMode.VIDEO`, with real numbers.
