"""Pure helpers for the Phase 9 online-inference path.

Deliberately dependency-light (numpy only, no snowflake/streamlit imports) for two
reasons:

* `streamlit/inference_app.py` needs it, and a Streamlit-in-Snowflake app can only
  import files that sit next to it on its stage — `scripts/deploy_streamlit.py`
  uploads this module as a flat `serving.py` alongside the app.
* it makes the two operations that are easy to get silently wrong — sensor
  standardisation and the single-tensor input layout — unit-testable without a
  Snowflake session (see `tests/test_core.py`).

The rules encoded here must stay in step with training:

* sensors are standardised with **train-split** mean/std (`src/data.py`), with the
  same `std < 1e-6 -> 1.0` guard for degenerate channels;
* the registered models take one tensor, laid out as
  `src/model.RegistryInferenceWrapper` expects (image, sensor, or
  `[image | sensor]` concatenated for fusion);
* the models regress `log(distance)` when `conf/train.yaml: data.log_target` is
  true, so predictions must be exponentiated to get metres.
"""

from __future__ import annotations

import numpy as np

MODALITIES = ("sensor", "image", "fusion")

# Order matters: it must match conf/train.yaml `data.sensor_channels`, which is the
# order src/data.py builds the sensor matrix in (and therefore the order the model's
# first Linear layer was trained on). speed / wheel_speed_mean are deliberately
# absent — they leak traffic-flow correlation.
SENSOR_CHANNELS: tuple[str, ...] = (
    "STEERING_ANGLE",
    "ACCEL_X",
    "ACCEL_Y",
    "ACCEL_Z",
    "GYRO_X",
    "GYRO_Y",
    "GYRO_Z",
)

STD_FLOOR = 1e-6


def standardize(raw: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    """Standardise raw sensor values with train-split statistics.

    Mirrors `src/data.py`'s scaler exactly, including its guard against a
    (near-)constant channel, which would otherwise divide by ~0.
    """
    raw = np.asarray(raw, dtype=np.float32)
    means = np.asarray(means, dtype=np.float32)
    stds = np.array(stds, dtype=np.float32, copy=True)
    if not (raw.shape[-1] == means.shape[-1] == stds.shape[-1]):
        raise ValueError(
            f"channel count mismatch: raw={raw.shape[-1]}, mean={means.shape[-1]}, "
            f"std={stds.shape[-1]}"
        )
    stds[stds < STD_FLOOR] = 1.0
    return ((raw - means) / stds).astype(np.float32)


def build_payload(
    modality: str,
    embedding: np.ndarray | None,
    sensors_scaled: np.ndarray | None,
    image_dim: int = 576,
) -> np.ndarray:
    """Build the single-row (1, n) input tensor for a modality's service call.

    `RegistryInferenceWrapper.forward()` takes ONE positional tensor and splits it
    internally at `image_dim` for fusion, so the concatenation order here
    (image first, then sensor) is load-bearing — swapping it produces predictions
    that look plausible but are meaningless.
    """
    if modality not in MODALITIES:
        raise ValueError(f"modality must be one of {MODALITIES}, got {modality!r}")

    if modality in ("image", "fusion"):
        if embedding is None:
            raise ValueError(f"modality={modality} needs an image embedding")
        embedding = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if embedding.shape[0] != image_dim:
            raise ValueError(
                f"expected a {image_dim}-dim embedding, got {embedding.shape[0]}"
            )
    if modality in ("sensor", "fusion"):
        if sensors_scaled is None:
            raise ValueError(f"modality={modality} needs sensor values")
        sensors_scaled = np.asarray(sensors_scaled, dtype=np.float32).reshape(-1)

    if modality == "image":
        payload = embedding
    elif modality == "sensor":
        payload = sensors_scaled
    else:
        payload = np.concatenate([embedding, sensors_scaled])
    return payload.reshape(1, -1).astype(np.float32)


def to_distance(prediction: float | np.ndarray, log_target: bool = True) -> np.ndarray:
    """Map a raw model output back to metres."""
    pred = np.asarray(prediction, dtype=np.float64)
    return np.exp(pred) if log_target else pred


def resolve_function_name(functions: list[dict], preferred: str = "forward") -> str:
    """Pick the inference method to call on a served model version.

    Phase 7 registers a plain `torch.nn.Module` (`RegistryInferenceWrapper`), so the
    Model Registry derives the callable from the module's own method and exposes it as
    **`forward`** — not `predict` (confirmed against a real deployment: calling
    `predict` raises `ValueError: There is no method with name predict available in the
    model ...`). Rather than hardcode either name, resolve it from the model version's
    own `show_functions()` output so this keeps working if the model is ever logged as
    a custom model with a `predict` method instead.

    Args:
        functions: `ModelVersion.show_functions()` output as a list of dicts.
        preferred: method to prefer when the model exposes more than one.
    """
    if not functions:
        raise ValueError("model version exposes no callable functions")
    names = []
    for fn in functions:
        target = fn.get("target_method") or fn.get("name")
        if target:
            names.append(str(target))
    if not names:
        raise ValueError(f"could not read a target method from {functions!r}")
    for candidate in (preferred, "predict", "forward"):
        for name in names:
            if name.lower() == candidate.lower():
                return name
    return names[0]


def service_name_for(modality: str) -> str:
    """Name of the Phase 9 inference service for a modality."""
    if modality not in MODALITIES:
        raise ValueError(f"modality must be one of {MODALITIES}, got {modality!r}")
    return f"LEAD_DISTANCE_{modality.upper()}_SVC"


def model_name_for(modality: str) -> str:
    """Name of the Phase 7 registered model for a modality."""
    if modality not in MODALITIES:
        raise ValueError(f"modality must be one of {MODALITIES}, got {modality!r}")
    return f"LEAD_DISTANCE_{modality.upper()}"
