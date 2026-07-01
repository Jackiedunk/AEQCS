-- AEQCS nightly PostgreSQL maintenance.
-- Run against the AEQCS database during the post-close quiet window.

VACUUM (ANALYZE) minute_bar_hot;
VACUUM (ANALYZE) factor_values;
VACUUM (ANALYZE) event_log;
VACUUM (ANALYZE) event_consumptions;
VACUUM (ANALYZE) news_raw;
VACUUM (ANALYZE) proposals;
VACUUM (ANALYZE) signal_log;
VACUUM (ANALYZE) cooccurrence_cache;
VACUUM (ANALYZE) doc_chunks;
