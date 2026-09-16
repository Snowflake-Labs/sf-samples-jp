"""Phase 9 — online inference UI.

Sends a single sample to the SPCS inference services deployed by
`scripts/deploy_serving.py` and shows what each of the three ablation models
predicts for the distance to the lead vehicle, next to the radar ground truth.

Two things this UI is really for:

1. **Round-trip online inference on Snowflake.** The models are hosted as
   long-running SPCS services (`ML.LEAD_DISTANCE_*_SVC`); this app calls them
   request/response from inside Snowflake, so a prediction takes milliseconds
   rather than a batch job.
2. **Making the ablation tangible.** The sensor sliders let you push the
   ego-dynamics channels around and watch the sensor-only model's prediction
   swing while the image and fusion models barely move — the interactive version
   of "the distance signal is in the camera, not the ego sensors".

Two correctness details that are easy to get wrong and produce plausible-looking
but wrong numbers (see `src/data.py` / `conf/train.yaml`):

* The models were trained on sensor channels standardised with **train-split**
  mean/std, so raw slider values must be standardised the same way before being
  sent. The stats are recomputed here in SQL over exactly the rows `src/data.py`
  keeps (train split, non-null distance and non-null channels), using
  `STDDEV_POP` to match numpy's default `ddof=0`.
* The models regress **log(distance)**, so the service output must be
  exponentiated to get metres.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from snowflake.ml.registry import Registry
from snowflake.snowpark.context import get_active_session

# The prediction-path logic (sensor standardisation, single-tensor layout,
# log-distance inversion) lives in src/serving.py so it can be unit-tested without
# a Snowflake session. scripts/deploy_streamlit.py uploads that module next to this
# app as a flat `serving.py`; the `src.serving` fallback is for running/linting this
# file from a checkout.
try:
    import serving
except ModuleNotFoundError:  # pragma: no cover - only hit outside the SiS stage
    from src import serving  # type: ignore[no-redef]

DATABASE = "CAR_MULTIMODAL_AI_DB"
ML_SCHEMA = "ML"
CURATED = f"{DATABASE}.CURATED"
IMAGE_DIM = 576
SENSOR_CHANNELS = list(serving.SENSOR_CHANNELS)
MODALITIES = list(serving.MODALITIES)
COLORS = {"sensor": "#c44e52", "image": "#4c72b0", "fusion": "#55a868"}

session = get_active_session()

st.set_page_config(page_title="Lead-Vehicle Distance — Online Inference", layout="wide")
st.title("Lead-Vehicle Distance — Online Inference")
st.caption(
    "Sends one sample to the sensor / image / fusion models hosted as Snowpark Container "
    "Services inference endpoints, and compares each prediction against the radar ground truth."
)

# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
VALID_FILTER = " AND ".join(
    ["s.DISTANCE IS NOT NULL"] + [f"s.{c} IS NOT NULL" for c in SENSOR_CHANNELS]
)


@st.cache_data(ttl=300)
def load_scaler() -> pd.DataFrame:
    """Train-split mean/std per sensor channel — must mirror src/data.py's scaler.

    STDDEV_POP (not STDDEV/STDDEV_SAMP) because src/data.py uses
    `train.sensors.std(axis=0)`, i.e. numpy's population std (ddof=0).
    """
    aggs = ", ".join(
        f"AVG(s.{c}) AS {c}_MEAN, STDDEV_POP(s.{c}) AS {c}_STD" for c in SENSOR_CHANNELS
    )
    return session.sql(
        f"""
        SELECT {aggs}
        FROM {CURATED}.SENSORS s
        JOIN {CURATED}.SPLITS sp ON sp.SEGMENT_ID = s.SEGMENT
        JOIN {CURATED}.FEATURES f ON f.SAMPLE_ID = s.SAMPLE_ID
        WHERE sp.SPLIT = 'train' AND {VALID_FILTER}
        """
    ).to_pandas()


@st.cache_data(ttl=300)
def load_channel_ranges() -> pd.DataFrame:
    """Min/max per channel over the whole dataset — used to bound the sliders."""
    aggs = ", ".join(f"MIN(s.{c}) AS {c}_MIN, MAX(s.{c}) AS {c}_MAX" for c in SENSOR_CHANNELS)
    return session.sql(
        f"SELECT {aggs} FROM {CURATED}.SENSORS s WHERE {VALID_FILTER}"
    ).to_pandas()


@st.cache_data(ttl=300)
def load_test_segments() -> list[str]:
    rows = session.sql(
        f"""
        SELECT DISTINCT s.SEGMENT
        FROM {CURATED}.SENSORS s
        JOIN {CURATED}.SPLITS sp ON sp.SEGMENT_ID = s.SEGMENT
        WHERE sp.SPLIT = 'test' AND {VALID_FILTER}
        ORDER BY s.SEGMENT
        """
    ).collect()
    return [r["SEGMENT"] for r in rows]


@st.cache_data(ttl=300)
def load_samples(segment: str) -> pd.DataFrame:
    channel_cols = ", ".join(f"s.{c}" for c in SENSOR_CHANNELS)
    return session.sql(
        f"""
        SELECT s.SAMPLE_ID, s.FRAME_IDX, s.DISTANCE, s.SPEED, {channel_cols}
        FROM {CURATED}.SENSORS s
        JOIN {CURATED}.SPLITS sp ON sp.SEGMENT_ID = s.SEGMENT
        JOIN {CURATED}.FEATURES f ON f.SAMPLE_ID = s.SAMPLE_ID
        WHERE s.SEGMENT = '{segment}' AND {VALID_FILTER}
        ORDER BY s.FRAME_IDX
        """
    ).to_pandas()


@st.cache_data(ttl=300)
def load_embedding(sample_id: str) -> np.ndarray:
    """The frozen-backbone image embedding for one sample (Phase 5 output).

    ARRAY columns come back from to_pandas() as JSON strings rather than lists
    (the same behaviour src/data.py works around), so parse defensively.
    """
    import json

    rows = session.sql(
        f"SELECT EMBEDDING FROM {CURATED}.FEATURES WHERE SAMPLE_ID = '{sample_id}'"
    ).collect()
    if not rows:
        raise ValueError(f"no embedding found for sample_id={sample_id}")
    raw = rows[0]["EMBEDDING"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    return np.asarray(raw, dtype=np.float32)


@st.cache_data(ttl=300)
def presigned_image_url(sample_id: str, kind: str = "cropped") -> str | None:
    try:
        rows = session.sql(
            f"SELECT GET_PRESIGNED_URL(@{CURATED}.IMAGES_STAGE, "
            f"'{kind}/{sample_id}.jpg', 3600) AS URL"
        ).collect()
        return rows[0]["URL"] if rows else None
    except Exception:  # noqa: BLE001 - image preview is optional, never break the page
        return None


@st.cache_resource
def model_versions() -> dict:
    """Latest registered version per modality — the one deploy_serving.py deployed.

    Mirrors `scripts/deploy_serving.py: resolve_latest_version()` (can't import it
    here: a Streamlit-in-Snowflake app only has its own stage files, not scripts/).
    """
    reg = Registry(session=session, database_name=DATABASE, schema_name=ML_SCHEMA)
    out = {}
    for m in MODALITIES:
        try:
            model = reg.get_model(serving.model_name_for(m))
            versions = model.show_versions()
            if versions.empty:
                continue
            latest = versions.sort_values("created_on").iloc[-1]["name"]
            out[m] = model.version(latest)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"{m}: model not found in the Registry ({exc})")
    return out


def service_states() -> dict[str, str]:
    rows = session.sql(
        f"SHOW SERVICES LIKE 'LEAD_DISTANCE_%_SVC' IN SCHEMA {DATABASE}.{ML_SCHEMA}"
    ).collect()
    states = {}
    for r in rows:
        d = r.as_dict()
        name = str(d.get("name", ""))
        for m in MODALITIES:
            if name.upper() == serving.service_name_for(m):
                states[m] = str(d.get("status") or d.get("state") or "UNKNOWN")
    return states


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #
def standardize(raw: np.ndarray, scaler: pd.DataFrame) -> np.ndarray:
    """Standardise raw slider/sample values with the train-split stats from SQL."""
    means = np.array([float(scaler.iloc[0][f"{c}_MEAN"]) for c in SENSOR_CHANNELS], np.float32)
    stds = np.array([float(scaler.iloc[0][f"{c}_STD"]) for c in SENSOR_CHANNELS], np.float32)
    return serving.standardize(raw, means, stds)


def predict(modality: str, mv, payload: np.ndarray) -> tuple[float, float]:
    """Call the service; returns (distance_metres, round_trip_ms).

    The method name is resolved from the model version rather than hardcoded: Phase 7
    registers a plain nn.Module, which the Registry exposes as `forward`, not `predict`.
    """
    service = serving.service_name_for(modality)
    function_name = serving.resolve_function_name(mv.show_functions())
    t0 = time.time()
    out = mv.run(
        payload,
        function_name=function_name,
        service_name=f"{DATABASE}.{ML_SCHEMA}.{service}",
    )
    elapsed_ms = 1000 * (time.time() - t0)
    value = float(np.asarray(out).reshape(-1)[0])
    return float(serving.to_distance(value, log_target=True)), elapsed_ms


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
states = service_states()
if not states:
    st.error(
        "No inference services found. Deploy them first:\n\n"
        "`python3 scripts/deploy_serving.py`"
    )
    st.stop()

cols = st.columns(len(MODALITIES))
for col, m in zip(cols, MODALITIES, strict=False):
    state = states.get(m, "not deployed")
    col.metric(f"{m} service", state)

segments = load_test_segments()
if not segments:
    st.error("No test-split samples found. Run Phase 2/5 first.")
    st.stop()

st.sidebar.header("Input sample")
segment = st.sidebar.selectbox("Test-split segment", segments)
samples = load_samples(segment)
if samples.empty:
    st.warning("This segment has no valid-label samples.")
    st.stop()

labels = [
    f"frame {int(r.FRAME_IDX):4d}  (radar {r.DISTANCE:.1f} m)" for r in samples.itertuples()
]
choice = st.sidebar.selectbox("Sample", range(len(labels)), format_func=lambda i: labels[i])
row = samples.iloc[choice]
sample_id = row["SAMPLE_ID"]
truth_m = float(row["DISTANCE"])

scaler = load_scaler()
ranges = load_channel_ranges()

st.sidebar.header("Sensor what-if")
st.sidebar.caption(
    "Ego-dynamics inputs. Move these and compare how much each model reacts: the "
    "image-only model is *exactly* invariant (it has no sensor input at all), the "
    "sensor-only model swings hardest because ego dynamics are all it has, and fusion "
    "reacts but stays anchored by the image."
)
use_overrides = st.sidebar.checkbox("Override sensor values", value=False)
raw_sensors = np.array([float(row[c]) for c in SENSOR_CHANNELS], dtype=np.float32)
if use_overrides:
    edited = []
    for i, c in enumerate(SENSOR_CHANNELS):
        lo = float(ranges.iloc[0][f"{c}_MIN"])
        hi = float(ranges.iloc[0][f"{c}_MAX"])
        edited.append(
            st.sidebar.slider(c, min_value=lo, max_value=hi, value=float(raw_sensors[i]))
        )
    raw_sensors = np.array(edited, dtype=np.float32)
    if st.sidebar.button("Reset to sample values"):
        st.rerun()

left, right = st.columns([1, 2])

with left:
    st.subheader("Input frame")
    url = presigned_image_url(sample_id, "cropped")
    if url:
        st.image(url, caption=f"{sample_id} (cropped region fed to the backbone)")
    else:
        st.info("Cropped frame preview unavailable.")
    st.caption(
        "⚠ Public-road dashcam footage — blur before presenting."
    )
    st.metric("Radar ground truth", f"{truth_m:.2f} m")
    st.caption(f"`speed` at this frame: {float(row['SPEED']):.1f} m/s (not a model input)")

with right:
    st.subheader("Predictions from the deployed services")
    embedding = load_embedding(sample_id)
    sensors_scaled = standardize(raw_sensors, scaler)
    mvs = model_versions()

    results = []
    to_call = []
    for m in MODALITIES:
        if m not in mvs or states.get(m, "").upper() not in ("RUNNING", "READY"):
            results.append({"modality": m, "pred_m": np.nan, "ms": np.nan, "error": "unavailable"})
        else:
            to_call.append(m)

    # Issue the three service calls concurrently. Measured against a real deployment,
    # a single `mv.run(..., service_name=...)` round trip costs ~5-10 s almost
    # entirely in fixed per-call overhead (scoring 1 row costs the same as scoring
    # 200), so running the modalities sequentially would make every interaction feel
    # like the sum of all three rather than the slowest one.
    if to_call:
        with ThreadPoolExecutor(max_workers=len(to_call)) as pool:
            futures = {
                pool.submit(
                    predict,
                    m,
                    mvs[m],
                    serving.build_payload(m, embedding, sensors_scaled, image_dim=IMAGE_DIM),
                ): m
                for m in to_call
            }
            for future in as_completed(futures):
                m = futures[future]
                try:
                    pred_m, ms = future.result()
                    results.append({"modality": m, "pred_m": pred_m, "ms": ms, "error": ""})
                except Exception as exc:  # noqa: BLE001 - show which model failed, keep the rest
                    results.append(
                        {"modality": m, "pred_m": np.nan, "ms": np.nan, "error": str(exc)[:200]}
                    )

    # Restore a stable display order (as_completed returns them out of order).
    order = {m: i for i, m in enumerate(MODALITIES)}
    results.sort(key=lambda r: order[r["modality"]])

    # Signed error vs. the radar ground truth (negative = underestimate). Falls back to
    # the failure message itself when a model has no prediction to compare.
    for r in results:
        r["error_m"] = r["pred_m"] - truth_m if not np.isnan(r["pred_m"]) else np.nan

    res_df = pd.DataFrame(results)

    metric_cols = st.columns(len(MODALITIES))
    for col, r in zip(metric_cols, results, strict=True):
        if np.isnan(r["pred_m"]):
            col.metric(r["modality"].capitalize(), "n/a", help=r["error"])
        else:
            col.metric(
                r["modality"].capitalize(),
                f"{r['pred_m']:.2f} m",
                delta=f"{r['pred_m'] - truth_m:+.2f} m vs radar",
                delta_color="off",
            )
            col.caption(f"{r['ms']:.0f} ms round trip")

    plotted = res_df.dropna(subset=["pred_m"])
    if not plotted.empty:
        fig = go.Figure(
            go.Bar(
                x=[m.capitalize() for m in plotted["modality"]],
                y=plotted["pred_m"],
                marker_color=[COLORS[m] for m in plotted["modality"]],
                text=[f"{v:.1f} m" for v in plotted["pred_m"]],
                textposition="outside",
            )
        )
        fig.add_hline(
            y=truth_m,
            line_dash="dash",
            line_color="black",
            annotation_text=f"Radar ground truth {truth_m:.1f} m",
        )
        fig.update_layout(
            height=380, template="plotly_white", showlegend=False,
            yaxis_title="Predicted distance [m]",
        )
        st.plotly_chart(fig, use_container_width=True)

    display_df = res_df.rename(
        columns={
            "modality": "Model",
            "pred_m": "Predicted [m]",
            "error_m": "Error vs radar [m]",
            "ms": "Latency [ms]",
            "error": "Status",
        }
    )
    st.dataframe(
        display_df.style.format(
            {"Predicted [m]": "{:.2f}", "Error vs radar [m]": "{:+.2f}", "Latency [ms]": "{:.0f}"},
            na_rep="n/a",
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Latency is dominated by fixed per-call overhead on the in-Snowflake service-function "
        "path (measured: scoring 1 row costs about the same as scoring 200), not by the model "
        "itself. The three calls above are issued concurrently, so the wait is the slowest "
        "model rather than the sum. For genuinely low-latency clients, deploy with "
        "`--ingress` and call the service's HTTPS endpoint directly."
    )

st.divider()
st.info(
    "**How this works** — each model was registered in the Model Registry by Phase 7 and "
    "deployed to a Snowpark Container Services inference service by Phase 9 "
    "(`scripts/deploy_serving.py`). This app standardises the sensor channels with the "
    "train-split statistics, sends the 576-dim image embedding and/or the 7 ego-dynamics "
    "channels to the service, and exponentiates the returned value (the models regress "
    "log-distance). Nothing leaves Snowflake: the services have no public endpoint and are "
    "called from inside the account."
)
