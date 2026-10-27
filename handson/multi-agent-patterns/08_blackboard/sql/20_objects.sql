-- 08_blackboard/sql/20_objects.sql
-- ブラックボード: 追記のみの掲示板、購読者ごとの受信箱、購読者ごとのビューとストリーム、確認用ビュー。
-- エージェント同士は直接やり取りせず、掲示板の状態の変化（新しい項目）に反応して動く。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.BOARD_ITEMS (
    ITEM_ID        STRING NOT NULL PRIMARY KEY,
    RUN_ID         STRING NOT NULL,         -- 1 回の投稿から派生した項目をまとめる ID
    KIND           STRING NOT NULL,         -- NOTE | CANDIDATES | DEDUPE | CRITERIA | PROPOSALS
    PRODUCER       STRING NOT NULL,         -- human | decompose | dedupe | criteria | assemble
    PARENT_ITEM_ID STRING,                  -- 来歴（どの項目から作られたか）
    PAYLOAD        VARIANT,
    CREATED_AT     TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
) CHANGE_TRACKING = TRUE
  COMMENT = 'Pattern 08: shared, append-only blackboard. Items are never updated.';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.BOARD_INBOX (
    SUBSCRIBER STRING NOT NULL,
    ITEM_ID    STRING NOT NULL,
    RUN_ID     STRING,
    STATUS     STRING NOT NULL,             -- NEW | WAITING | DONE | ERROR
    ATTEMPTS   NUMBER DEFAULT 0,
    LAST_ERROR STRING,
    UPDATED_AT TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (SUBSCRIBER, ITEM_ID)
) COMMENT = 'Pattern 08: per-subscriber inbox (idempotent processing state)';

-- 購読者ごとに「消費する種類だけ」を見るビューとストリーム。自分が書いた種類では起動しない（ループ防止）。
CREATE OR REPLACE VIEW <% db %>.INTERNAL.BOARD_V_DECOMPOSE
COMMENT = 'Pattern 08: board items consumed by the decompose subscriber'
AS SELECT ITEM_ID, RUN_ID, KIND FROM <% db %>.INTERNAL.BOARD_ITEMS WHERE KIND IN ('NOTE');
CREATE OR REPLACE STREAM <% db %>.INTERNAL.BOARD_S_DECOMPOSE ON VIEW <% db %>.INTERNAL.BOARD_V_DECOMPOSE APPEND_ONLY = TRUE;

CREATE OR REPLACE VIEW <% db %>.INTERNAL.BOARD_V_DEDUPE
COMMENT = 'Pattern 08: board items consumed by the dedupe subscriber'
AS SELECT ITEM_ID, RUN_ID, KIND FROM <% db %>.INTERNAL.BOARD_ITEMS WHERE KIND IN ('CANDIDATES');
CREATE OR REPLACE STREAM <% db %>.INTERNAL.BOARD_S_DEDUPE ON VIEW <% db %>.INTERNAL.BOARD_V_DEDUPE APPEND_ONLY = TRUE;

CREATE OR REPLACE VIEW <% db %>.INTERNAL.BOARD_V_CRITERIA
COMMENT = 'Pattern 08: board items consumed by the criteria subscriber'
AS SELECT ITEM_ID, RUN_ID, KIND FROM <% db %>.INTERNAL.BOARD_ITEMS WHERE KIND IN ('CANDIDATES');
CREATE OR REPLACE STREAM <% db %>.INTERNAL.BOARD_S_CRITERIA ON VIEW <% db %>.INTERNAL.BOARD_V_CRITERIA APPEND_ONLY = TRUE;

CREATE OR REPLACE VIEW <% db %>.INTERNAL.BOARD_V_ASSEMBLE
COMMENT = 'Pattern 08: board items consumed by the assemble subscriber'
AS SELECT ITEM_ID, RUN_ID, KIND FROM <% db %>.INTERNAL.BOARD_ITEMS WHERE KIND IN ('DEDUPE', 'CRITERIA');
CREATE OR REPLACE STREAM <% db %>.INTERNAL.BOARD_S_ASSEMBLE ON VIEW <% db %>.INTERNAL.BOARD_V_ASSEMBLE APPEND_ONLY = TRUE;

CREATE OR REPLACE VIEW <% db %>.APP.V_BOARD_TIMELINE
COMMENT = 'Pattern 08: board items in time order, with the processing state of each subscriber'
AS
SELECT b.RUN_ID, b.CREATED_AT, b.KIND, b.PRODUCER, b.ITEM_ID, b.PARENT_ITEM_ID,
       ARRAY_SIZE(COALESCE(b.PAYLOAD:candidates, b.PAYLOAD:actions)) AS N,
       (SELECT LISTAGG(i.SUBSCRIBER || ':' || i.STATUS, ', ') WITHIN GROUP (ORDER BY i.SUBSCRIBER)
          FROM <% db %>.INTERNAL.BOARD_INBOX i WHERE i.ITEM_ID = b.ITEM_ID) AS CONSUMED_BY,
       b.PAYLOAD
FROM <% db %>.INTERNAL.BOARD_ITEMS b;

CREATE OR REPLACE VIEW <% db %>.APP.V_BOARD_INBOX
COMMENT = 'Pattern 08: subscriber inbox (errors and waiting items)'
AS
SELECT SUBSCRIBER, ITEM_ID, RUN_ID, STATUS, ATTEMPTS, LAST_ERROR, UPDATED_AT FROM <% db %>.INTERNAL.BOARD_INBOX;
