-- ============================================================
-- 01_setup_database.sql
-- Builds the base environment for car_multimodal_ai_sample.
--
-- Resources created:
--   - DATABASE     CAR_MULTIMODAL_AI_DB
--   - SCHEMA       RAW / CURATED / ML / APP
--   - WAREHOUSE    MULTIMODAL_WH (SMALL)
--   - COMPUTE POOL MULTIMODAL_CPU_POOL (CPU_X64_M)  -- embedding extraction, small-scale training
--   - COMPUTE POOL MULTIMODAL_GPU_POOL (GPU_NV_S)   -- optional; see §3
--   - COMPUTE POOL MULTIMODAL_SERVING_POOL (CPU_X64_S) -- Phase 9 online inference services
--   - ROLE         MULTIMODAL_APP_ROLE
--   - Stage        RAW.RAW_STAGE / CURATED.IMAGES_STAGE / CURATED.FEATURES_STAGE / CURATED.JOB_STAGE
--   - WORKSPACE    ML.CAR_MULTIMODAL_AI  -- holds the Phase 3/4/6 Notebooks in Workspaces
--                  (.ipynb) files; scripts/upload_notebooks.py pushes them here
--
-- Execution role: ACCOUNTADMIN (required to create DATABASE/WAREHOUSE/COMPUTE POOL/ROLE)
-- How to run    : cortex sql, or Run All in a Snowsight Worksheet
--
-- Portability: does not depend on account-specific values (account name, pre-existing
-- SYSTEM_COMPUTE_POOL_* etc.). Everything uses IF NOT EXISTS and is idempotent. Runs as-is
-- on any Snowflake account.
-- ============================================================

USE ROLE ACCOUNTADMIN;

-- -- Database / Schema ---------------------------------------------------------
CREATE DATABASE IF NOT EXISTS CAR_MULTIMODAL_AI_DB
  COMMENT = 'car_multimodal_ai_sample: comma2k19 E2E multimodal AI reference on Snowflake';

CREATE SCHEMA IF NOT EXISTS CAR_MULTIMODAL_AI_DB.RAW
  COMMENT = 'Phase 1-2: raw ingestion (segments, raw logs/video) and segment ledger';
CREATE SCHEMA IF NOT EXISTS CAR_MULTIMODAL_AI_DB.CURATED
  COMMENT = 'Phase 2-5: curated tables (SENSORS/SPLITS) and image/feature stages';
CREATE SCHEMA IF NOT EXISTS CAR_MULTIMODAL_AI_DB.ML
  COMMENT = 'Phase 6-8: Experiments, Model Registry, Datasets (default ML schema)';
CREATE SCHEMA IF NOT EXISTS CAR_MULTIMODAL_AI_DB.APP
  COMMENT = 'Phase 8: Streamlit comparison dashboard';

-- -- Warehouse -------------------------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS MULTIMODAL_WH
  WAREHOUSE_SIZE = SMALL
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE
  COMMENT        = 'car_multimodal_ai_sample: SQL / Notebook orchestration warehouse';

-- -- Compute Pool (CPU, required) ------------------------------------------------
-- Used by ML Jobs (Phase 1, 2, 5, 7) and Notebooks on Container Runtime (Phase 3, 4, 6).
-- MAX_NODES=10: headroom for multi-node ML Jobs (e.g. scaling out Phase 7's distributed training).
CREATE COMPUTE POOL IF NOT EXISTS MULTIMODAL_CPU_POOL
  MIN_NODES = 1
  MAX_NODES = 10
  INSTANCE_FAMILY = CPU_X64_M
  AUTO_SUSPEND_SECS = 600
  AUTO_RESUME = TRUE
  COMMENT = 'car_multimodal_ai_sample: CPU pool for ML Jobs / Notebooks (Phase 1,2,5,7)';

-- -- Compute Pool (GPU, optional) -------------------------------------------------
-- GPU is not required (CPU is already known to give adequate accuracy).
-- This is an optional demo of multi-node/GPU distributed training "scaling". If GPU
-- instances aren't available on your account, you can skip this CREATE statement
-- (Phase 7 completes fine with just the CPU pool).
CREATE COMPUTE POOL IF NOT EXISTS MULTIMODAL_GPU_POOL
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = GPU_NV_S
  AUTO_SUSPEND_SECS = 300
  AUTO_RESUME = TRUE
  COMMENT = 'car_multimodal_ai_sample: OPTIONAL GPU pool for Phase 7 scale-out demo';

-- -- Compute Pool (serving, Phase 9) ----------------------------------------------
-- Hosts the Model Serving inference services created in Phase 9
-- (scripts/deploy_serving.py -> ModelVersion.create_service()). Deliberately a
-- SEPARATE pool from MULTIMODAL_CPU_POOL: an inference service stays resident to
-- answer requests, which keeps its pool from ever auto-suspending. Sharing the
-- ML-Jobs pool would therefore mean paying for idle Phase 1/2/5/7 capacity for as
-- long as any service is up. Three small services (sensor/image/fusion) fit
-- comfortably on CPU_X64_S; MAX_NODES=3 leaves room for one node each if
-- Snowflake decides to spread them.
CREATE COMPUTE POOL IF NOT EXISTS MULTIMODAL_SERVING_POOL
  MIN_NODES = 1
  MAX_NODES = 3
  INSTANCE_FAMILY = CPU_X64_S
  AUTO_SUSPEND_SECS = 600
  AUTO_RESUME = TRUE
  COMMENT = 'car_multimodal_ai_sample: Phase 9 online inference services (Model Serving on SPCS)';

-- -- Role ---------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS MULTIMODAL_APP_ROLE
  COMMENT = 'car_multimodal_ai_sample: single application role (no multi-participant RBAC)';

GRANT USAGE ON DATABASE CAR_MULTIMODAL_AI_DB TO ROLE MULTIMODAL_APP_ROLE;
GRANT USAGE ON SCHEMA CAR_MULTIMODAL_AI_DB.RAW      TO ROLE MULTIMODAL_APP_ROLE;
GRANT USAGE ON SCHEMA CAR_MULTIMODAL_AI_DB.CURATED  TO ROLE MULTIMODAL_APP_ROLE;
GRANT USAGE ON SCHEMA CAR_MULTIMODAL_AI_DB.ML       TO ROLE MULTIMODAL_APP_ROLE;
GRANT USAGE ON SCHEMA CAR_MULTIMODAL_AI_DB.APP      TO ROLE MULTIMODAL_APP_ROLE;
GRANT USAGE ON WAREHOUSE MULTIMODAL_WH TO ROLE MULTIMODAL_APP_ROLE;

GRANT USAGE, MONITOR  ON COMPUTE POOL MULTIMODAL_CPU_POOL TO ROLE MULTIMODAL_APP_ROLE;
GRANT OPERATE, MODIFY ON COMPUTE POOL MULTIMODAL_CPU_POOL TO ROLE MULTIMODAL_APP_ROLE;
-- The GPU pool GRANTs only take effect if the pool was actually created. If you skipped
-- creating it, comment out the following two statements.
GRANT USAGE, MONITOR  ON COMPUTE POOL MULTIMODAL_GPU_POOL TO ROLE MULTIMODAL_APP_ROLE;
GRANT OPERATE, MODIFY ON COMPUTE POOL MULTIMODAL_GPU_POOL TO ROLE MULTIMODAL_APP_ROLE;
-- Phase 9 serving pool (Model Serving services run here)
GRANT USAGE, MONITOR  ON COMPUTE POOL MULTIMODAL_SERVING_POOL TO ROLE MULTIMODAL_APP_ROLE;
GRANT OPERATE, MODIFY ON COMPUTE POOL MULTIMODAL_SERVING_POOL TO ROLE MULTIMODAL_APP_ROLE;

-- Schema-level CREATE privileges (for ML Jobs / Notebooks / Registry / Experiments / Streamlit)
GRANT CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT, CREATE DYNAMIC TABLE,
      CREATE TASK, CREATE NETWORK RULE, CREATE SECRET
  ON SCHEMA CAR_MULTIMODAL_AI_DB.RAW TO ROLE MULTIMODAL_APP_ROLE;
GRANT CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT, CREATE DYNAMIC TABLE
  ON SCHEMA CAR_MULTIMODAL_AI_DB.CURATED TO ROLE MULTIMODAL_APP_ROLE;
GRANT CREATE EXPERIMENT, CREATE MODEL, CREATE DATASET, CREATE MODEL MONITOR, CREATE TABLE,
      CREATE STAGE, CREATE TAG, CREATE WORKSPACE, CREATE SERVICE
  ON SCHEMA CAR_MULTIMODAL_AI_DB.ML TO ROLE MULTIMODAL_APP_ROLE;
GRANT CREATE STREAMLIT, CREATE STAGE
  ON SCHEMA CAR_MULTIMODAL_AI_DB.APP TO ROLE MULTIMODAL_APP_ROLE;

-- Needed to run ML Jobs (so execution status is visible on Snowsight's Jobs page)
GRANT MONITOR EXECUTION ON ACCOUNT TO ROLE MULTIMODAL_APP_ROLE;

-- Grant the role to the executing user (replace with the user who will use this role)
GRANT ROLE MULTIMODAL_APP_ROLE TO ROLE ACCOUNTADMIN;

-- -- Stages (DIRECTORY enabled: for file listing / URL access) -----------------------
USE DATABASE CAR_MULTIMODAL_AI_DB;

CREATE STAGE IF NOT EXISTS RAW.RAW_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  DIRECTORY  = (ENABLE = TRUE)
  COMMENT    = 'Phase 1: Chunk_1 raw segments (.hevc + processed_log/ + global_pose/)';
ALTER STAGE RAW.RAW_STAGE SET DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS CURATED.IMAGES_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  DIRECTORY  = (ENABLE = TRUE)
  COMMENT    = 'Phase 2: extracted frames (full/ and cropped/)';
ALTER STAGE CURATED.IMAGES_STAGE SET DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS CURATED.FEATURES_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  DIRECTORY  = (ENABLE = TRUE)
  COMMENT    = 'Phase 5: 576-dim frozen-backbone embeddings (Parquet)';
ALTER STAGE CURATED.FEATURES_STAGE SET DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS CURATED.MISC_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  DIRECTORY  = (ENABLE = TRUE)
  COMMENT    = 'Misc uploads: splits.json intermediate files, conf snapshots';
ALTER STAGE CURATED.MISC_STAGE SET DIRECTORY = (ENABLE = TRUE);

-- For ML Jobs payloads (SSE encryption is required for SPCS Compute Pool FUSE mounts)
CREATE STAGE IF NOT EXISTS CURATED.JOB_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT    = 'ML Jobs payload staging (submit_file/submit_directory)';

GRANT READ, WRITE ON STAGE RAW.RAW_STAGE            TO ROLE MULTIMODAL_APP_ROLE;
GRANT READ, WRITE ON STAGE CURATED.IMAGES_STAGE      TO ROLE MULTIMODAL_APP_ROLE;
GRANT READ, WRITE ON STAGE CURATED.FEATURES_STAGE    TO ROLE MULTIMODAL_APP_ROLE;
GRANT READ, WRITE ON STAGE CURATED.MISC_STAGE        TO ROLE MULTIMODAL_APP_ROLE;
GRANT READ, WRITE ON STAGE CURATED.JOB_STAGE         TO ROLE MULTIMODAL_APP_ROLE;

-- -- Workspace (holds the Phase 3/4/6 Notebooks in Workspaces .ipynb files) -----------
-- Legacy `CREATE NOTEBOOK ... FROM stage` is deprecated in favor of Notebooks in
-- Workspaces (Snowflake disables creating new Legacy Notebooks starting Sept 1, 2026).
-- scripts/upload_notebooks.py pushes notebooks/src/conf into this workspace's live
-- version and commits it; open/run them from Snowsight > Projects > Workspaces.
-- CREATE WORKSPACE has no IF NOT EXISTS-safe OR REPLACE (replacing would wipe existing
-- files), so IF NOT EXISTS is used and re-running this script leaves an already-created
-- workspace's contents untouched.
CREATE WORKSPACE IF NOT EXISTS ML.CAR_MULTIMODAL_AI
  COMMENT = 'car_multimodal_ai_sample: Phase 3/4/6 Notebooks in Workspaces (.ipynb + src/ + conf/)';

GRANT READ, WRITE ON WORKSPACE ML.CAR_MULTIMODAL_AI TO ROLE MULTIMODAL_APP_ROLE;

-- -- Verification ---------------------------------------------------------------
SELECT CURRENT_TIMESTAMP() AS executed_at;
SHOW SCHEMAS IN DATABASE CAR_MULTIMODAL_AI_DB;
SHOW WAREHOUSES LIKE 'MULTIMODAL_WH';
SHOW COMPUTE POOLS LIKE 'MULTIMODAL_%';
SHOW STAGES IN DATABASE CAR_MULTIMODAL_AI_DB;
SHOW WORKSPACES LIKE 'CAR_MULTIMODAL_AI' IN SCHEMA CAR_MULTIMODAL_AI_DB.ML;
