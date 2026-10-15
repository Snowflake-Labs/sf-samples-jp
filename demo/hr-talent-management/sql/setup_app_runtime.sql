-- ============================================================================
-- Snowflake App Runtime へのデプロイ準備（アプリ ⇔ Postgres の通信と秘密情報）
-- ============================================================================
-- 実行: ACCOUNTADMIN。<...> を自分の環境の値に置き換えてから実行する。
--   <YOUR_PG_HOST>      Postgres インスタンスのホスト名（SHOW POSTGRES INSTANCES の host）
--   <YOUR_ACCOUNT_HOST> アカウントのホスト（例: myorg-myaccount.snowflakecomputing.com）
--   <YOUR_PG_POLICY>    Postgres インスタンスに付けたネットワークポリシー名
--
-- アプリから Postgres に届くまでに、次の 3 か所すべてで許可が要る:
--   1. アプリから外への通信 … EAI（Postgres:5432 とアカウントホスト:443）
--   2. Postgres への受信     … Postgres のネットワークポリシーに Snowflake の送信元 IP 帯
--   3. アカウントへの受信    … アカウントにネットワークポリシーがある場合のみ（下の 4. を参照）
--
-- 2. と 4. の IP 帯での許可は、2026 年 10 月時点の App Runtime の仕様（アプリの通信が
-- Snowflake の送信元 IP 帯から出る）に合わせた対応。仕様が変わると不要になる可能性がある。
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- ----------------------------------------------------------------------------
-- 1. アプリから外への通信（EAI）
--    :443 は、アプリの起動時に runtime_manager がビルド成果物を取りに行くのに必要
-- ----------------------------------------------------------------------------
CREATE OR REPLACE NETWORK RULE HR_ANALYTICS.STAGING.HR_APP_EGRESS_RULE
    MODE = EGRESS
    TYPE = HOST_PORT
    VALUE_LIST = ('<YOUR_PG_HOST>:5432', '<YOUR_ACCOUNT_HOST>:443')
    COMMENT = 'HR app -> Postgres (5432) and account host (443)';

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION HR_APP_EAI
    ALLOWED_NETWORK_RULES = (HR_ANALYTICS.STAGING.HR_APP_EGRESS_RULE)
    ENABLED = TRUE;

-- ----------------------------------------------------------------------------
-- 2. Postgres への受信: Snowflake の送信元 IP 帯を Postgres のネットワークポリシーに入れる
--    IP 帯は次で確認する（有効期限があるので、期限前に見直す）
--      SELECT SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES();
--    リージョンによって値が違う。結果の ipv4_prefix をすべて <SNOWFLAKE_EGRESS_IP_RANGES> に並べる
--    作業 PC 用の IP は Postgres 側から見える値（SELECT inet_client_addr();）にする。
--    社内のゲートウェイを経由していると、checkip などで見える IP とは違う
-- ----------------------------------------------------------------------------
-- ALTER NETWORK RULE <YOUR_PG_INGRESS_RULE> SET VALUE_LIST = (
--     '<YOUR_PC_IP>/32', '<SNOWFLAKE_EGRESS_IP_RANGES>');

-- ----------------------------------------------------------------------------
-- 3. 秘密情報（app.yml の secrets から完全修飾名で参照する）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE SECRET HR_ANALYTICS.STAGING.HR_PG_PASSWORD_SECRET
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_PG_PASSWORD>';

-- SESSION_SECRET はログイン Cookie の署名用。openssl rand -hex 32 などで作ったランダム値
CREATE OR REPLACE SECRET HR_ANALYTICS.STAGING.HR_SESSION_SECRET
    TYPE = GENERIC_STRING
    SECRET_STRING = '<RANDOM_64_HEX>';

-- ----------------------------------------------------------------------------
-- 4. アカウントにネットワークポリシーがある場合
--    アプリのコンテナは Snowflake の送信元 IP 帯からアカウントに認証し直す。
--    許可していないと 390422 INCOMING_REQUEST_BLOCKED でコンテナが起動しない。
--    確認: SHOW PARAMETERS LIKE 'NETWORK_POLICY' IN ACCOUNT;
--
--    アカウントのポリシーは全員のログインに効くため、UNSET したり置き換えたりしない。
--    ALLOWED_IP_LIST だけで運用しているポリシーは SET で丸ごと置き換わるので、
--    今のリストを DESC NETWORK POLICY で控えてから、既存の値 + 送信元 IP 帯を指定する。
-- ----------------------------------------------------------------------------
-- DESC NETWORK POLICY <YOUR_ACCOUNT_POLICY>;
-- ALTER NETWORK POLICY <YOUR_ACCOUNT_POLICY> SET ALLOWED_IP_LIST = (
--     <既存の値をすべて>, '<SNOWFLAKE_EGRESS_IP_RANGES>');
