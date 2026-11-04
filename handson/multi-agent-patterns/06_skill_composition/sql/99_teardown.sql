-- 06_skill_composition/sql/99_teardown.sql
-- Delete only the pattern 06 database, including its stage and skills.
USE ROLE ACCOUNTADMIN;
DROP DATABASE IF EXISTS <% skill_db %>;
