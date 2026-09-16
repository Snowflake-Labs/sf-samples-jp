-- ============================================================
-- 03_teardown.sql
-- Complete teardown script for car_multimodal_ai_sample.
--
-- Removes:
--   - SERVICE       ML.LEAD_DISTANCE_{SENSOR,IMAGE,FUSION}_SVC (Phase 9 inference services)
--   - DATABASE      CAR_MULTIMODAL_AI_DB (cascades to RAW/CURATED/ML/APP)
--   - WAREHOUSE     MULTIMODAL_WH
--   - COMPUTE POOL  MULTIMODAL_CPU_POOL / MULTIMODAL_GPU_POOL / MULTIMODAL_SERVING_POOL
--   - EXTERNAL ACCESS INTEGRATION HF_ACCESS_INTEGRATION
--   - ROLE          MULTIMODAL_APP_ROLE
--
-- Execution role: ACCOUNTADMIN
-- WARNING: this operation is irreversible. Verify you're targeting the right account first.
-- ============================================================

SELECT CURRENT_ACCOUNT() AS account, CURRENT_USER() AS exec_user, CURRENT_TIMESTAMP() AS exec_at;

USE ROLE ACCOUNTADMIN;

-- Phase 9 inference services first: a COMPUTE POOL that still has services on it
-- cannot be dropped ("Cannot drop compute pool with active services"). DROP DATABASE
-- would cascade these too, but dropping them explicitly first keeps the pool DROP
-- below safe regardless of ordering/timing.
DROP SERVICE IF EXISTS CAR_MULTIMODAL_AI_DB.ML.LEAD_DISTANCE_SENSOR_SVC;
DROP SERVICE IF EXISTS CAR_MULTIMODAL_AI_DB.ML.LEAD_DISTANCE_IMAGE_SVC;
DROP SERVICE IF EXISTS CAR_MULTIMODAL_AI_DB.ML.LEAD_DISTANCE_FUSION_SVC;

DROP EXTERNAL ACCESS INTEGRATION IF EXISTS HF_ACCESS_INTEGRATION;
DROP DATABASE IF EXISTS CAR_MULTIMODAL_AI_DB;
DROP WAREHOUSE IF EXISTS MULTIMODAL_WH;
DROP COMPUTE POOL IF EXISTS MULTIMODAL_CPU_POOL;
DROP COMPUTE POOL IF EXISTS MULTIMODAL_GPU_POOL;
DROP COMPUTE POOL IF EXISTS MULTIMODAL_SERVING_POOL;
DROP ROLE IF EXISTS MULTIMODAL_APP_ROLE;

-- -- Verify removal (empty results are OK) --------------------------------------
SHOW DATABASES      LIKE 'CAR_MULTIMODAL_AI_DB';
SHOW WAREHOUSES     LIKE 'MULTIMODAL_WH';
SHOW COMPUTE POOLS  LIKE 'MULTIMODAL_%';
SHOW ROLES          LIKE 'MULTIMODAL_APP_ROLE';
