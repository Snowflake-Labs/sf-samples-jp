-- 06_skill_composition/sql/99_teardown.sql
-- パターン 06 のデータベース（ステージとスキルを含む）だけを削除する。
USE ROLE ACCOUNTADMIN;
DROP DATABASE IF EXISTS <% skill_db %>;
