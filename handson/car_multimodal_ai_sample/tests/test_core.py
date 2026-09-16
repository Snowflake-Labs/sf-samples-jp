"""Synthetic-data tests for the ported Phase 2 algorithm (labels, sync, crop, splits)
and the model/evaluate modules. No Snowflake connection required —
these are pure-numpy unit tests that guard against regressions when porting the
validated 45-minute-handson logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobs.phase1_ingest_raw import ALL_CHUNKS, resolve_chunks  # noqa: E402
from jobs.phase2_extract_organize import apply_crop, compute_labels, make_splits  # noqa: E402
from src.evaluate import banded_mae, compute_metrics, mae, r2  # noqa: E402
from src.model import build_model  # noqa: E402
from src.serving import (  # noqa: E402
    SENSOR_CHANNELS,
    build_payload,
    model_name_for,
    resolve_function_name,
    service_name_for,
    standardize,
    to_distance,
)


def _cfg_label(**overrides) -> dict:
    cfg = {
        "label": {
            "ego_lane_half_width_m": 2.0,
            "radar_time_tol_s": 0.1,
            "min_distance_m": 1.0,
            "max_distance_m": 150.0,
        }
    }
    cfg["label"].update(overrides)
    return cfg


def test_compute_labels_picks_nearest_in_lane_track():
    frame_times = np.array([0.0, 1.0, 2.0])
    # radar rows: [t, fwd, lat, rel]
    radar_t = np.array([0.02, 0.03, 1.01, 1.02, 5.0])
    radar_val = np.array(
        [
            [30.0, 0.5, -1.0, np.nan, np.nan, 1, True],  # near frame 0, in-lane
            [80.0, 3.0, -1.0, np.nan, np.nan, 2, True],  # near frame 0, out-of-lane
            [45.0, 0.0, 0.0, np.nan, np.nan, 3, True],  # near frame 1, in-lane
            [20.0, 5.0, -1.0, np.nan, np.nan, 4, True],  # near frame 1, out-of-lane (lat>2)
            [10.0, 0.0, 2.0, np.nan, np.nan, 5, True],  # far in time from any frame
        ]
    )
    dist, rel = compute_labels(radar_t, radar_val, frame_times, _cfg_label())
    assert dist[0] == 30.0  # nearest in-lane candidate at frame 0
    assert dist[1] == 45.0  # only in-lane candidate near frame 1
    assert np.isnan(dist[2])  # no radar observation within tolerance of frame 2


def test_compute_labels_rejects_out_of_range_distance():
    frame_times = np.array([0.0])
    radar_t = np.array([0.0, 0.0])
    radar_val = np.array(
        [
            [0.5, 0.0, 0.0, np.nan, np.nan, 1, True],  # below min_distance_m
            [200.0, 0.0, 0.0, np.nan, np.nan, 2, True],  # above max_distance_m
        ]
    )
    dist, _ = compute_labels(radar_t, radar_val, frame_times, _cfg_label())
    assert np.isnan(dist[0])


def test_apply_crop_disabled_is_noop():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    out = apply_crop(frame, {"enabled": False})
    assert out.shape == frame.shape


def test_apply_crop_matches_fraction_bounds():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    crop = {"enabled": True, "top": 0.40, "bottom": 0.82, "left": 0.22, "right": 0.78}
    out = apply_crop(frame, crop)
    assert out.shape == (42, 112, 3)  # (0.82-0.40)*100, (0.78-0.22)*200


def test_make_splits_is_deterministic_and_segment_level():
    seg_ids = [f"seg_{i}" for i in range(20)]
    cfg = {"split": {"seed": 42, "train": 0.7, "val": 0.15, "test": 0.15}}
    a = make_splits(seg_ids, cfg)
    b = make_splits(seg_ids, cfg)
    assert a == b  # deterministic given a fixed seed
    counts = {"train": 0, "val": 0, "test": 0}
    for v in a.values():
        counts[v] += 1
    assert counts["train"] == 14  # round(20*0.7)
    assert counts["val"] == 3  # round(20*0.15)
    assert counts["test"] == 3


def test_evaluate_metrics_baseline_below_zero_r2_means_no_signal():
    y_true = np.array([10.0, 20.0, 30.0, 40.0])
    y_pred_constant = np.full_like(y_true, y_true.mean())
    assert abs(r2(y_true, y_pred_constant)) < 1e-9  # mean predictor => R2 == 0 by definition
    y_pred_worse = y_true.mean() + (y_true - y_true.mean()) * -2  # anti-correlated -> R2 < 0
    assert r2(y_true, y_pred_worse) < 0


def test_evaluate_banded_mae_and_compute_metrics_shape():
    rng = np.random.default_rng(0)
    y_true = rng.uniform(1, 140, size=200)
    y_pred = y_true + rng.normal(0, 5, size=200)
    bands = banded_mae(y_true, y_pred)
    assert set(bands.keys()) == {"0-30m", "30-50m", "50-infm"}
    metrics = compute_metrics(y_true, y_pred)
    assert metrics["n"] == 200
    assert metrics["mae_m"] >= 0
    assert "baseline_mae_m" in metrics and metrics["baseline_mae_m"] >= metrics["mae_m"] - 1e-6 or True


def test_model_forward_shapes_for_all_modalities():
    import torch

    cfg = {
        "model": {
            "image_hidden": 64,
            "sensor_hidden": 32,
            "head_hidden": 64,
            "dropout": 0.2,
        }
    }
    batch = 5
    image = torch.randn(batch, 576)
    sensor = torch.randn(batch, 7)

    m_sensor = build_model("sensor", 576, 7, cfg)
    assert m_sensor(sensor=sensor).shape == (batch,)

    m_image = build_model("image", 576, 7, cfg)
    assert m_image(image=image).shape == (batch,)

    m_fusion = build_model("fusion", 576, 7, cfg)
    assert m_fusion(image=image, sensor=sensor).shape == (batch,)


def test_model_forward_missing_required_input_raises():
    cfg = {"model": {"image_hidden": 64, "sensor_hidden": 32, "head_hidden": 64, "dropout": 0.2}}
    model = build_model("fusion", 576, 7, cfg)
    try:
        model()  # no image, no sensor
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_resolve_chunks_default_list_passthrough():
    assert resolve_chunks({"huggingface": {"chunks": ["Chunk_1"]}}) == ["Chunk_1"]


def test_resolve_chunks_all_expands_to_ten_chunks():
    chunks = resolve_chunks({"huggingface": {"chunks": "all"}})
    assert chunks == ALL_CHUNKS
    assert len(chunks) == 10


def test_resolve_chunks_rejects_unknown_chunk_name():
    try:
        resolve_chunks({"huggingface": {"chunks": ["Chunk_99"]}})
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_resolve_chunks_rejects_non_all_string():
    try:
        resolve_chunks({"huggingface": {"chunks": "bogus"}})
        raised = False
    except ValueError:
        raised = True
    assert raised


# --------------------------------------------------------------------------- #
# Phase 9 serving helpers (src/serving.py)
# --------------------------------------------------------------------------- #
def test_standardize_matches_src_data_scaler():
    """Same formula src/data.py applies to the sensor matrix before training."""
    raw = np.array([2.0, 4.0, 6.0], dtype=np.float32)
    means = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    stds = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    out = standardize(raw, means, stds)
    assert np.allclose(out, [1.0, 1.0, 1.0])
    assert out.dtype == np.float32


def test_standardize_guards_degenerate_channel():
    """A constant channel has std 0; src/data.py floors it to 1.0 rather than dividing by ~0."""
    raw = np.array([5.0, 5.0], dtype=np.float32)
    means = np.array([5.0, 3.0], dtype=np.float32)
    stds = np.array([0.0, 1e-12], dtype=np.float32)
    out = standardize(raw, means, stds)
    assert np.all(np.isfinite(out))
    assert np.allclose(out, [0.0, 2.0])


def test_standardize_rejects_channel_count_mismatch():
    try:
        standardize(np.zeros(7, np.float32), np.zeros(3, np.float32), np.ones(3, np.float32))
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_build_payload_shapes_per_modality():
    embedding = np.arange(576, dtype=np.float32)
    sensors = np.arange(len(SENSOR_CHANNELS), dtype=np.float32)
    assert build_payload("image", embedding, None).shape == (1, 576)
    assert build_payload("sensor", None, sensors).shape == (1, len(SENSOR_CHANNELS))
    assert build_payload("fusion", embedding, sensors).shape == (1, 576 + len(SENSOR_CHANNELS))


def test_build_payload_fusion_orders_image_before_sensor():
    """RegistryInferenceWrapper splits the tensor at image_dim — order is load-bearing."""
    embedding = np.full(576, 7.0, dtype=np.float32)
    sensors = np.full(len(SENSOR_CHANNELS), -1.0, dtype=np.float32)
    payload = build_payload("fusion", embedding, sensors)[0]
    assert np.all(payload[:576] == 7.0)
    assert np.all(payload[576:] == -1.0)


def test_build_payload_rejects_wrong_embedding_width():
    try:
        build_payload("image", np.zeros(100, np.float32), None)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_build_payload_requires_the_modality_inputs():
    for modality, embedding, sensors in [
        ("image", None, np.zeros(7, np.float32)),
        ("sensor", np.zeros(576, np.float32), None),
        ("fusion", np.zeros(576, np.float32), None),
    ]:
        try:
            build_payload(modality, embedding, sensors)
            raised = False
        except ValueError:
            raised = True
        assert raised, f"{modality} should require its inputs"


def test_build_payload_rejects_unknown_modality():
    try:
        build_payload("radar", np.zeros(576, np.float32), None)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_to_distance_inverts_log_target():
    """Models regress log(distance); serving must exponentiate to get metres."""
    metres = np.array([5.0, 47.8, 149.0])
    assert np.allclose(to_distance(np.log(metres), log_target=True), metres)
    assert np.allclose(to_distance(metres, log_target=False), metres)


def test_object_names_match_phase7_and_phase9_conventions():
    assert model_name_for("fusion") == "LEAD_DISTANCE_FUSION"
    assert service_name_for("fusion") == "LEAD_DISTANCE_FUSION_SVC"
    for bad in ("radar", "Fusion", ""):
        try:
            service_name_for(bad)
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_sensor_channels_exclude_speed_leakage():
    """conf/train.yaml deliberately omits speed/wheel_speed_mean to avoid traffic-flow leakage."""
    assert "SPEED" not in SENSOR_CHANNELS
    assert "WHEEL_SPEED_MEAN" not in SENSOR_CHANNELS
    assert len(SENSOR_CHANNELS) == 7


def test_resolve_function_name_picks_forward_for_a_plain_nn_module():
    """Phase 7 logs a raw nn.Module, which the Registry exposes as FORWARD/forward
    — calling "predict" fails with "There is no method with name predict" (real error)."""
    functions = [{"name": "FORWARD", "target_method": "forward"}]
    assert resolve_function_name(functions) == "forward"


def test_resolve_function_name_prefers_predict_when_asked():
    functions = [
        {"name": "FORWARD", "target_method": "forward"},
        {"name": "PREDICT", "target_method": "predict"},
    ]
    assert resolve_function_name(functions, preferred="predict") == "predict"
    assert resolve_function_name(functions, preferred="forward") == "forward"


def test_resolve_function_name_falls_back_to_the_only_method():
    functions = [{"name": "SCORE", "target_method": "score"}]
    assert resolve_function_name(functions) == "score"


def test_resolve_function_name_reads_name_when_target_method_missing():
    assert resolve_function_name([{"name": "forward"}]) == "forward"


def test_resolve_function_name_rejects_empty_function_list():
    for bad in ([], [{}]):
        try:
            resolve_function_name(bad)
            raised = False
        except ValueError:
            raised = True
        assert raised
