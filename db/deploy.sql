-- ============================================================================
-- Metallurgical Consultation & RAG System - Production deployment script
--
-- Creates the database (if missing), the schema, all tables/indexes/triggers,
-- and the reference data the application needs to boot (roles, consultation
-- categories, pricing plans, knowledge categories, system settings).
--
-- Usage (run once, connecting to the default "postgres" maintenance database
-- so the target database can be created):
--
--     psql -h <host> -U <admin-user> -d postgres -f db/deploy.sql
--
-- Idempotent: every statement uses IF NOT EXISTS / CREATE OR REPLACE / ON
-- CONFLICT DO NOTHING, so re-running this script against an already-deployed
-- database is safe and changes nothing.
--
-- Does NOT create demo/test accounts - that is a separate, dev-only step
-- (backend/scripts/seed_demo_data.py) and must never be run against production.
-- ============================================================================

\set ON_ERROR_STOP on
\set target_db onlinedb

\echo 'Step 1/3: ensuring database' :target_db 'exists...'
SELECT 'CREATE DATABASE ' || :'target_db' || ' ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'target_db')\gexec

\c :target_db

\echo 'Step 2/3: applying schema (extensions, tables, indexes, triggers)...'
\ir schema.sql

\echo 'Step 3/3: applying reference seed data...'
\ir seed.sql

\echo 'Done. Database' :target_db 'is ready.'
