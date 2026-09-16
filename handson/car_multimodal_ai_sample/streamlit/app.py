"""Ablation comparison dashboard.

Reads run history from ML Experiments and model metadata from the Model
Registry instead of a shared METRICS table (the 45-minute handson's approach,
`car_multimodal_handson/snowflake/streamlit/app.py`) — this is a Snowflake-
native reference implementation, so the comparison UI traces every displayed
metric back to a specific Experiment run and a specific Model Registry
version (run_id <-> model version).

Data access notes (confirmed against a real deployment):
`ExperimentTracking` has no `search_runs()` method — run history is read via
`SHOW RUNS IN EXPERIMENT <name>`, whose `metadata` column is a VARIANT/JSON
string with `status`, `metrics`, and `source_info` (no `params` sub-object in
this API version; modality is instead recovered from the run name prefix,
e.g. `SENSOR_1788332568`).
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from snowflake.ml.registry import Registry
from snowflake.snowpark.context import get_active_session

DATABASE = "CAR_MULTIMODAL_AI_DB"
EXPERIMENT_NAME = "LEAD_DISTANCE_ESTIMATION"
COLORS = {"sensor": "#c44e52", "image": "#4c72b0", "fusion": "#55a868"}
ORDER = ["sensor", "image", "fusion"]

session = get_active_session()

st.set_page_config(page_title="Lead-Vehicle Distance Estimation - Ablation Results", layout="wide")
st.title("Lead-Vehicle Distance Estimation - Ablation Results")
st.caption(
    "Radar is the teacher, camera is the student. Which modality holds the distance signal? "
    "(Comparison dashboard reading Snowflake ML Experiments / Model Registry)"
)


def _modality_from_run_name(name: str) -> str:
    prefix = name.split("_")[0].lower()
    return prefix if prefix in ORDER else "unknown"


@st.cache_data(ttl=30)
def load_runs() -> pd.DataFrame:
    try:
        rows = session.sql(
            f"SHOW RUNS IN EXPERIMENT {DATABASE}.ML.{EXPERIMENT_NAME}"
        ).collect()
    except Exception as exc:  # noqa: BLE001 - surface a friendly message instead of a stack trace
        st.warning(f"Experiment '{EXPERIMENT_NAME}' not found (Phase 7 hasn't run yet): {exc}")
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        meta = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]
        metrics = {k: v.get("value") for k, v in (meta.get("metrics") or {}).items()}
        records.append(
            {
                "RUN_NAME": r["name"],
                "MODALITY": _modality_from_run_name(r["name"]),
                "CREATED_ON": r["created_on"],
                "STATUS": meta.get("status"),
                **metrics,
            }
        )
    return pd.DataFrame(records)


@st.cache_data(ttl=30)
def load_models() -> pd.DataFrame:
    reg = Registry(session=session, database_name=DATABASE, schema_name="ML")
    try:
        return reg.show_models()
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Failed to read from Model Registry: {exc}")
        return pd.DataFrame()


runs_df = load_runs()
models_df = load_models()

if runs_df.empty:
    st.warning(
        "No training results yet. Please run `jobs/phase7_train_distributed.py` as an ML Job."
    )
    st.stop()

# -- Keep only the latest run per modality -----------------------------------
latest = runs_df.sort_values("CREATED_ON").drop_duplicates("MODALITY", keep="last")
latest = latest.set_index("MODALITY")
present = [m for m in ORDER if m in latest.index]

if not present:
    st.warning("Could not determine modality from any Experiment run. Check the run-name prefixes.")
    st.stop()


def _metric(row, name: str, default=float("nan")):
    return row[name] if name in row and pd.notna(row[name]) else default


col1, col2 = st.columns(2)

with col1:
    st.subheader("Test-set MAE [m]  (lower is better)")
    maes = [_metric(latest.loc[m], "test_mae_m") for m in present]
    fig = go.Figure(
        go.Bar(
            x=[m.capitalize() for m in present],
            y=maes,
            marker_color=[COLORS.get(m, "#888") for m in present],
            text=[f"{v:.1f} m" if pd.notna(v) else "n/a" for v in maes],
            textposition="outside",
        )
    )
    baseline_vals = [_metric(latest.loc[m], "baseline_mae_m") for m in present]
    baseline = next((v for v in baseline_vals if pd.notna(v)), None)
    if baseline:
        fig.add_hline(
            y=baseline, line_dash="dash", line_color="gray",
            annotation_text=f"Baseline (mean-value prediction) {baseline:.1f} m",
        )
    fig.update_layout(height=400, template="plotly_white", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("R\u00b2  (1.0 = perfect prediction, <=0 = loses to mean-value prediction)")
    r2s = [_metric(latest.loc[m], "test_r2") for m in present]
    fig = go.Figure(
        go.Bar(
            x=[m.capitalize() for m in present],
            y=r2s,
            marker_color=[COLORS.get(m, "#888") for m in present],
            text=[f"{v:.3f}" if pd.notna(v) else "n/a" for v in r2s],
            textposition="outside",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="R\u00b2=0")
    fig.update_layout(height=400, template="plotly_white", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# -- Distance-band MAE table --------------------------------------------------
band_cols = ["mae_0-30m", "mae_30-50m", "mae_50-infm"]
if all(c in latest.columns for c in band_cols):
    st.subheader("MAE by distance band [m] - near-range accuracy is the safety-relevant one")
    band_df = latest.loc[present, band_cols].copy()
    band_df.columns = ["0-30 m", "30-50 m", "50 m+"]
    st.dataframe(
        band_df.style.format("{:.2f}").highlight_min(axis=0, color="#d4edda"),
        use_container_width=True,
    )

st.subheader("Experiment runs (run_name <-> modality <-> key metrics)")
show_cols = [c for c in runs_df.columns if c in ("RUN_NAME", "MODALITY", "CREATED_ON", "STATUS", "test_mae_m", "test_r2")]
st.dataframe(runs_df[show_cols] if show_cols else runs_df, use_container_width=True)

st.subheader("Model Registry - registered models (modality <-> model version mapping)")
if not models_df.empty:
    st.dataframe(models_df, use_container_width=True)
else:
    st.info("No models registered in the Model Registry yet.")

st.divider()
st.info(
    "**Why `speed` is excluded from the inputs**  \n"
    "In this data, `speed` correlates with lead-vehicle distance at +0.63 (faster = less "
    "congested = farther away). That's an incidental correlation from traffic flow, and "
    "wouldn't hold on a different road. Including `speed` pushes sensor-only R\u00b2 up to "
    "\u22480.26, which would undermine the core finding that \"sensor alone can't solve this\" "
    "- so it's excluded from the training inputs."
)
