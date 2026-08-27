-- Reference data required for the application to function.
SET search_path TO metag, public;

INSERT INTO metag.roles (code, name) VALUES
  ('customer', 'Customer'),
  ('expert', 'Metallurgical Expert'),
  ('admin', 'Administrator'),
  ('superadmin', 'Super Administrator')
ON CONFLICT (code) DO NOTHING;

INSERT INTO metag.consultation_categories (code, name, sort_order) VALUES
  ('material_selection', 'Material Selection', 1),
  ('heat_treatment', 'Heat Treatment', 2),
  ('welding', 'Welding', 3),
  ('casting', 'Casting', 4),
  ('forging', 'Forging', 5),
  ('failure_analysis', 'Failure Analysis', 6),
  ('metallography', 'Metallography', 7),
  ('mechanical_properties', 'Mechanical Properties', 8),
  ('corrosion', 'Corrosion', 9),
  ('surface_treatment', 'Surface Treatment', 10),
  ('standards_specification', 'Standards/Specification', 11),
  ('testing', 'Testing', 12),
  ('general', 'General Metallurgical Consultation', 13)
ON CONFLICT (code) DO NOTHING;

INSERT INTO metag.pricing_plans (code, name, description, price_inr) VALUES
  ('basic', 'Basic Consultation', 'Standard AI-assisted, expert-verified answer.', 500.00),
  ('detailed', 'Detailed Metallurgical Analysis', 'In-depth analysis with extended expert review.', 1000.00),
  ('failure_analysis', 'Failure-Analysis Consultation', 'Dedicated failure investigation consultation.', 2500.00),
  ('expert_meeting', 'Expert Consultation / Video Meeting', 'Live session with a metallurgical expert.', 5000.00)
ON CONFLICT (code) DO NOTHING;

-- Top-level knowledge categories; children (e.g. 'Carbon steels' under 'Materials') are added via the admin panel.
INSERT INTO metag.knowledge_categories (name, sort_order) VALUES
  ('Materials', 1),
  ('Processes', 2),
  ('Testing', 3),
  ('Failure Analysis', 4)
ON CONFLICT (name) WHERE parent_id IS NULL DO NOTHING;

INSERT INTO metag.system_settings (key, value, description) VALUES
  ('allow_external_knowledge', 'false', 'When false, the AI must answer only from retrieved, approved documents and must not fall back on general model knowledge.'),
  ('default_currency', '"INR"', 'Default currency for pricing and payments.')
ON CONFLICT (key) DO NOTHING;
