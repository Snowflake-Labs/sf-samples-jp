-- ============================================================
-- 04_deploy_streamlit.sql
-- Uploads streamlit/app.py to the APP schema and creates the STREAMLIT object (Phase 8).
--
-- Prerequisite: streamlit/app.py and streamlit/environment.yml must already be uploaded to
--   the stage. e.g.
--     PUT file://streamlit/app.py @CAR_MULTIMODAL_AI_DB.APP.STREAMLIT_STAGE AUTO_COMPRESS=FALSE;
--     PUT file://streamlit/environment.yml @CAR_MULTIMODAL_AI_DB.APP.STREAMLIT_STAGE AUTO_COMPRESS=FALSE;
--
-- Execution role: MULTIMODAL_APP_ROLE (CREATE STREAMLIT privilege already granted in infra/01)
-- ============================================================

USE ROLE MULTIMODAL_APP_ROLE;
USE DATABASE CAR_MULTIMODAL_AI_DB;
USE SCHEMA APP;

CREATE STAGE IF NOT EXISTS APP.STREAMLIT_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  DIRECTORY  = (ENABLE = TRUE)
  COMMENT    = 'streamlit/app.py + environment.yml for the Phase 8 comparison dashboard';

CREATE STREAMLIT IF NOT EXISTS APP.LEAD_DISTANCE_DASHBOARD
  ROOT_LOCATION = '@CAR_MULTIMODAL_AI_DB.APP.STREAMLIT_STAGE'
  MAIN_FILE = 'app.py'
  QUERY_WAREHOUSE = 'MULTIMODAL_WH'
  COMMENT = 'Phase 8: sensor/image/fusion ablation comparison (Experiments + Registry)';

SHOW STREAMLITS LIKE 'LEAD_DISTANCE_DASHBOARD' IN SCHEMA APP;
