-- PostgreSQL full-text search backfill
-- Run AFTER data migration (migrate_sqlite_to_pg.py) completes.
-- Usage: docker compose exec -T db psql -U aquavir -d aquavir_kb -f init_pg_search.sql

-- Backfill search_vector for virus_master
UPDATE virus_master SET search_vector =
    to_tsvector('english', COALESCE(canonical_name, '')) ||
    to_tsvector('english', COALESCE(abbreviations, '')) ||
    to_tsvector('english', COALESCE(chinese_name, ''));

-- Verify
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE search_vector IS NOT NULL) AS indexed_count
FROM virus_master;
