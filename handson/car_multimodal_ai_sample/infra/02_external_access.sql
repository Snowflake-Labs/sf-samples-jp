-- ============================================================
-- 02_external_access.sql
-- Builds the external access needed to fetch comma2k19 Chunk_1.zip from Hugging Face.
--
-- Important: commaai/comma2k19 is a fully public dataset (gated=false / private=false).
--            No auth token is required (confirmed to work via anonymous access).
--            Only add a token via the optional section at the bottom if you hit rate limits.
--
-- Execution role: ACCOUNTADMIN (required to create NETWORK RULE / EXTERNAL ACCESS INTEGRATION)
-- ============================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE CAR_MULTIMODAL_AI_DB;
USE SCHEMA RAW;

-- -- Network Rule ---------------------------------------------------------------
-- Requests to huggingface.co get redirected not just to the CDN (domains under
-- *.cdn.hf.co) but, for large files, also to the Xet CAS backend
-- (cas-server.xethub.hf.co) and to two-level-subdomain signed CDN URLs
-- (e.g. us.aws.cdn.hf.co) (confirmed against a real account, as of 2026-09).
-- Snowflake NETWORK RULE wildcards only match "one level" (see the official docs), so
-- `*.cdn.hf.co` alone does not match `us.aws.cdn.hf.co` — each level needs to be listed
-- explicitly, e.g. `*.aws.cdn.hf.co`.
CREATE NETWORK RULE IF NOT EXISTS RAW.HF_NETWORK_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = (
    'huggingface.co',
    '*.huggingface.co',
    '*.hf.co',
    '*.cdn.hf.co',
    '*.aws.cdn.hf.co',
    '*.gcp.cdn.hf.co',
    '*.azure.cdn.hf.co',
    'cas-server.xethub.hf.co',
    '*.xethub.hf.co'
  )
  COMMENT = 'Egress to Hugging Face Hub + CDN (incl. 2-level regional CDN subdomains) + Xet CAS for comma2k19 dataset download (Phase 1)';

-- -- External Access Integration (default: no token) ----------------------------
CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS HF_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (RAW.HF_NETWORK_RULE)
  ENABLED = TRUE
  COMMENT = 'car_multimodal_ai_sample: anonymous access to Hugging Face (no token required)';

GRANT USAGE ON INTEGRATION HF_ACCESS_INTEGRATION TO ROLE MULTIMODAL_APP_ROLE;

-- -- PyPI (for ML Jobs' pip_requirements) ----------------------------------------
-- Phase 2 (av/PyAV is not preinstalled in the Container Runtime) and similar cases need
-- ML Jobs to reach PyPI to pip install packages. We use Snowflake's built-in network rule
-- (snowflake.external_access.pypi_rule).
CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS PYPI_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (snowflake.external_access.pypi_rule)
  ENABLED = TRUE
  COMMENT = 'car_multimodal_ai_sample: PyPI access for ML Job pip_requirements (e.g. av)';

GRANT USAGE ON INTEGRATION PYPI_ACCESS_INTEGRATION TO ROLE MULTIMODAL_APP_ROLE;

-- -- PyTorch Hub (for Phase 5's frozen-backbone pretrained weights) ----------------
-- torchvision's mobilenet_v3_small(weights=...) fetches ImageNet-pretrained weights from
-- download.pytorch.org. ML Jobs block external network access by default, so without this
-- integration Phase 5 fails with a URLError (confirmed against real data; see §10.5).
CREATE NETWORK RULE IF NOT EXISTS CURATED.PYTORCH_HUB_NETWORK_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('download.pytorch.org')
  COMMENT = 'car_multimodal_ai_sample: PyTorch Hub pretrained weight downloads (Phase 5 MobileNetV3-small)';

CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS PYTORCH_HUB_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (CURATED.PYTORCH_HUB_NETWORK_RULE)
  ENABLED = TRUE
  COMMENT = 'car_multimodal_ai_sample: PyTorch Hub access for Phase 5 frozen backbone weights';

GRANT USAGE ON INTEGRATION PYTORCH_HUB_ACCESS_INTEGRATION TO ROLE MULTIMODAL_APP_ROLE;

-- -- Verification -----------------------------------------------------------------
SHOW NETWORK RULES IN SCHEMA RAW;
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'HF_ACCESS_INTEGRATION';
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'PYPI_ACCESS_INTEGRATION';
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'PYTORCH_HUB_ACCESS_INTEGRATION';

-- ============================================================
-- Optional: only run this if anonymous access hits a rate limit.
-- Do not hardcode the HUGGINGFACE_TOKEN value on the command line or in code —
-- pass it into the $token variable at execution time instead (e.g. SnowSQL's -D flag,
-- or substitute it manually in Snowsight).
-- ============================================================
--
-- CREATE SECRET IF NOT EXISTS RAW.HF_TOKEN_SECRET
--   TYPE = GENERIC_STRING
--   SECRET_STRING = '<REPLACE_AT_RUNTIME_DO_NOT_COMMIT>'
--   COMMENT = 'Optional HF token to avoid anonymous rate limits';
--
-- CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION HF_ACCESS_INTEGRATION
--   ALLOWED_NETWORK_RULES = (RAW.HF_NETWORK_RULE)
--   ALLOWED_AUTHENTICATION_SECRETS = (RAW.HF_TOKEN_SECRET)
--   ENABLED = TRUE;
--
-- GRANT READ ON SECRET RAW.HF_TOKEN_SECRET TO ROLE MULTIMODAL_APP_ROLE;
