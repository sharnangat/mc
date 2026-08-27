-- Metallurgical Consultation & RAG System
-- Database: onlinedb | Schema: metag
-- Target: PostgreSQL 15+ with pgcrypto and pgvector extensions

CREATE SCHEMA IF NOT EXISTS metag;
SET search_path TO metag, public;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Embedding dimension depends on the embedding model chosen
-- (384 = sentence-transformers/all-MiniLM-L6-v2; adjust if a different model is used).

CREATE OR REPLACE FUNCTION metag.set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- Identity & access
-- =========================================================================

CREATE TABLE metag.roles (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL UNIQUE,              -- customer | expert | admin | superadmin
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE metag.users (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email               text NOT NULL UNIQUE,
  phone               text UNIQUE,
  password_hash       text NOT NULL,
  full_name           text NOT NULL,
  company_name        text,
  is_active           boolean NOT NULL DEFAULT true,
  is_email_verified   boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON metag.users
  FOR EACH ROW EXECUTE FUNCTION metag.set_updated_at();

CREATE TABLE metag.user_roles (
  user_id      uuid NOT NULL REFERENCES metag.users(id) ON DELETE CASCADE,
  role_id      uuid NOT NULL REFERENCES metag.roles(id) ON DELETE RESTRICT,
  assigned_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
);

-- =========================================================================
-- Consultation catalog
-- =========================================================================

CREATE TABLE metag.consultation_categories (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL UNIQUE,
  name        text NOT NULL,
  description text,
  is_active   boolean NOT NULL DEFAULT true,
  sort_order  int NOT NULL DEFAULT 0
);

CREATE TABLE metag.pricing_plans (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code                      text NOT NULL UNIQUE,   -- basic | detailed | failure_analysis | expert_meeting
  name                      text NOT NULL,
  description               text,
  price_inr                 numeric(10,2) NOT NULL CHECK (price_inr >= 0),
  consultation_category_id  uuid REFERENCES metag.consultation_categories(id),  -- NULL = applies to any category
  is_active                 boolean NOT NULL DEFAULT true,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_pricing_plans_updated_at BEFORE UPDATE ON metag.pricing_plans
  FOR EACH ROW EXECUTE FUNCTION metag.set_updated_at();

-- =========================================================================
-- Knowledge base (source-controlled, admin-curated)
-- =========================================================================

CREATE TABLE metag.knowledge_categories (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   uuid REFERENCES metag.knowledge_categories(id) ON DELETE CASCADE,
  name        text NOT NULL,
  sort_order  int NOT NULL DEFAULT 0
);

CREATE TABLE metag.knowledge_documents (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title               text NOT NULL,
  document_type       text NOT NULL CHECK (document_type IN (
                        'standard','handbook','internal_report','customer_document',
                        'lab_procedure','heat_treatment_procedure','welding_procedure',
                        'material_specification','research_paper','other')),
  standard_name       text,      -- e.g. 'ASTM E8'
  edition_year        int,
  revision            text,
  source_owner        text,      -- e.g. 'ASM', 'ASTM', 'ISO', 'BIS', 'Internal'
  licence_status      text NOT NULL DEFAULT 'unlicensed'
                        CHECK (licence_status IN ('owned','licensed','public_domain','internal','unlicensed')),
  access_permission   text NOT NULL DEFAULT 'restricted'
                        CHECK (access_permission IN ('public','internal','restricted','admin_only')),
  -- Admin must explicitly enable a document before the RAG engine may retrieve from it
  -- (this is the source-level access control required by the licensing rules).
  is_enabled_for_ai   boolean NOT NULL DEFAULT false,
  indexing_status     text NOT NULL DEFAULT 'pending'
                        CHECK (indexing_status IN ('pending','processing','indexed','failed','disabled')),
  file_path           text NOT NULL,
  file_hash           text,
  uploaded_by         uuid REFERENCES metag.users(id),
  uploaded_at         timestamptz NOT NULL DEFAULT now(),
  last_indexed_at     timestamptz,
  notes               text
);

CREATE INDEX idx_knowledge_documents_enabled ON metag.knowledge_documents(is_enabled_for_ai);

CREATE TABLE metag.document_category_map (
  document_id  uuid NOT NULL REFERENCES metag.knowledge_documents(id) ON DELETE CASCADE,
  category_id  uuid NOT NULL REFERENCES metag.knowledge_categories(id) ON DELETE CASCADE,
  PRIMARY KEY (document_id, category_id)
);

CREATE TABLE metag.document_chunks (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id    uuid NOT NULL REFERENCES metag.knowledge_documents(id) ON DELETE CASCADE,
  chunk_index    int NOT NULL,
  page_number    int,
  section        text,
  clause_number  text,
  content_text   text NOT NULL,
  embedding      vector(384), -- sentence-transformers/all-MiniLM-L6-v2
  token_count    int,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_index)
);

-- hnsw (not ivfflat): ivfflat's clustering is trained at index-build time, so with
-- little/no data it has severe recall problems (can miss exact matches under
-- ORDER BY ... LIMIT) until the table is large and re-indexed. hnsw builds
-- incrementally and stays accurate from the first row.
CREATE INDEX idx_document_chunks_embedding ON metag.document_chunks
  USING hnsw (embedding vector_cosine_ops);

-- =========================================================================
-- System configuration & prompt versioning
-- =========================================================================

CREATE TABLE metag.system_settings (
  key         text PRIMARY KEY,
  value       jsonb NOT NULL,
  description text,
  updated_by  uuid REFERENCES metag.users(id),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE metag.prompt_templates (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  version        text NOT NULL,
  system_prompt  text NOT NULL,
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);

-- =========================================================================
-- Queries (consultations)
-- =========================================================================

CREATE SEQUENCE metag.query_code_seq START 1;

CREATE TABLE metag.queries (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_code                text UNIQUE,        -- e.g. MET-2026-000123, assigned by trigger below
  customer_id               uuid NOT NULL REFERENCES metag.users(id),
  consultation_category_id  uuid NOT NULL REFERENCES metag.consultation_categories(id),
  pricing_plan_id           uuid NOT NULL REFERENCES metag.pricing_plans(id),
  question_text             text NOT NULL,
  priority                  text NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal','high','urgent')),
  status                    text NOT NULL DEFAULT 'pending_payment' CHECK (status IN (
                              'pending_payment','paid','ai_processing','draft_ready',
                              'under_expert_review','more_info_requested','approved',
                              'rejected','sent','closed')),
  assigned_expert_id        uuid REFERENCES metag.users(id),
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_queries_customer ON metag.queries(customer_id);
CREATE INDEX idx_queries_status ON metag.queries(status);

CREATE TRIGGER trg_queries_updated_at BEFORE UPDATE ON metag.queries
  FOR EACH ROW EXECUTE FUNCTION metag.set_updated_at();

CREATE OR REPLACE FUNCTION metag.generate_query_code() RETURNS trigger AS $$
BEGIN
  IF NEW.query_code IS NULL THEN
    NEW.query_code := 'MET-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('metag.query_code_seq')::text, 6, '0');
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_queries_query_code BEFORE INSERT ON metag.queries
  FOR EACH ROW EXECUTE FUNCTION metag.generate_query_code();

CREATE TABLE metag.query_attachments (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id         uuid NOT NULL REFERENCES metag.queries(id) ON DELETE CASCADE,
  attachment_type  text NOT NULL CHECK (attachment_type IN (
                     'chemical_composition','hardness_result','tensile_result',
                     'heat_treatment_cycle','microstructure_photo','spectro_report',
                     'test_report','failure_photo','drawing_specification',
                     'welding_detail','pwht_detail','other')),
  file_name        text NOT NULL,
  file_path        text NOT NULL,
  uploaded_by      uuid REFERENCES metag.users(id),
  uploaded_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_query_attachments_query ON metag.query_attachments(query_id);

-- =========================================================================
-- Payments
-- =========================================================================

CREATE TABLE metag.payments (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id            uuid NOT NULL REFERENCES metag.queries(id),
  customer_id         uuid NOT NULL REFERENCES metag.users(id),
  pricing_plan_id     uuid NOT NULL REFERENCES metag.pricing_plans(id),
  amount_inr          numeric(10,2) NOT NULL CHECK (amount_inr >= 0),
  currency            text NOT NULL DEFAULT 'INR',
  gateway             text NOT NULL DEFAULT 'razorpay',
  gateway_order_id    text,
  gateway_payment_id  text,
  status              text NOT NULL DEFAULT 'created' CHECK (status IN ('created','paid','failed','refunded')),
  raw_response        jsonb,
  paid_at             timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_payments_query ON metag.payments(query_id);

-- =========================================================================
-- AI drafting, citations, expert review, final answer
-- =========================================================================

CREATE TABLE metag.ai_answers (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id                  uuid NOT NULL REFERENCES metag.queries(id) ON DELETE CASCADE,
  prompt_template_id        uuid REFERENCES metag.prompt_templates(id),
  model_name                text NOT NULL,
  model_version             text NOT NULL,
  technical_conclusion      text,
  technical_reasoning       text,
  recommended_action        text,
  insufficient_information  boolean NOT NULL DEFAULT false,
  status                    text NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft','under_review','approved','rejected','superseded')),
  created_at                timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_answers_query ON metag.ai_answers(query_id);

CREATE TABLE metag.ai_answer_sources (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_answer_id        uuid NOT NULL REFERENCES metag.ai_answers(id) ON DELETE CASCADE,
  document_id         uuid NOT NULL REFERENCES metag.knowledge_documents(id),
  -- SET NULL (not RESTRICT): cited_text below is already a snapshot of the quote,
  -- so a citation's audit record must survive the source document being re-ingested.
  document_chunk_id   uuid REFERENCES metag.document_chunks(id) ON DELETE SET NULL,
  relevance_score     numeric(5,4),
  cited_text          text,
  page_number         int,
  section             text,
  clause_number       text,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_answer_sources_answer ON metag.ai_answer_sources(ai_answer_id);

CREATE TABLE metag.expert_reviews (
  id                            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id                      uuid NOT NULL REFERENCES metag.queries(id) ON DELETE CASCADE,
  ai_answer_id                  uuid REFERENCES metag.ai_answers(id),
  expert_id                     uuid NOT NULL REFERENCES metag.users(id),
  action                        text NOT NULL CHECK (action IN (
                                  'approve','edit','reject','request_more_info','rerun_analysis','comment')),
  edited_technical_conclusion   text,
  edited_technical_reasoning    text,
  edited_recommended_action     text,
  comment                       text,
  created_at                    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_expert_reviews_query ON metag.expert_reviews(query_id);

CREATE TABLE metag.final_answers (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- One active final answer per query; a re-issued answer supersedes it via a new expert_review, not a new row.
  query_id                  uuid NOT NULL UNIQUE REFERENCES metag.queries(id),
  expert_review_id          uuid NOT NULL REFERENCES metag.expert_reviews(id),
  approved_by               uuid NOT NULL REFERENCES metag.users(id),
  final_technical_conclusion text NOT NULL,
  final_technical_reasoning  text,
  final_recommended_action   text,
  references_json            jsonb,   -- snapshot of the reference list shown to the customer
  sent_at                     timestamptz,
  sent_via                    text[] NOT NULL DEFAULT '{}',  -- website | email | whatsapp | sms
  created_at                  timestamptz NOT NULL DEFAULT now()
);

-- =========================================================================
-- Notifications & audit trail
-- =========================================================================

CREATE TABLE metag.notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES metag.users(id),
  query_id    uuid REFERENCES metag.queries(id),
  channel     text NOT NULL CHECK (channel IN ('website','email','whatsapp','sms')),
  message     text NOT NULL,
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
  sent_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE metag.audit_logs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type text NOT NULL,
  entity_id   uuid,
  action      text NOT NULL,
  actor_id    uuid REFERENCES metag.users(id),
  actor_role  text,
  before_data jsonb,
  after_data  jsonb,
  ip_address  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_logs_entity ON metag.audit_logs(entity_type, entity_id);
