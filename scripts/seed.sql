-- Seed data for Docker PostgreSQL
-- Usage: docker exec -i docker-postgres-1 psql -U nexus -d nexus < scripts/seed.sql

DELETE FROM tenant;
DELETE FROM public.user;
DELETE FROM tool;

INSERT INTO tenant (id, name, slug, status) VALUES
('11111111-1111-4111-8111-111111111111', 'Demo', 'demo', 'active');

INSERT INTO public.user (id, tenant_id, email, role) VALUES
('33333333-3333-4333-8333-333333333333', '11111111-1111-4111-8111-111111111111', 'admin@demo.com', 'tenant_admin');

INSERT INTO tool (id, tenant_id, name, description, purpose, endpoint_url, http_method, auth_type, input_schema, output_schema, tags, category, requires_approval, risk_level, enabled, version) VALUES
('00000000-0000-0000-0000-000000000010', '11111111-1111-4111-8111-111111111111', 'echo', 'Echoes back input', 'Testing', 'https://httpbin.org/post', 'POST', 'none', '{"type":"object","properties":{"msg":{"type":"string"}},"required":["msg"]}', '{}', '{test}', 'utilities', false, 'low', true, 1),
('00000000-0000-0000-0000-000000000020', '11111111-1111-4111-8111-111111111111', 'create_draft', 'Create a draft article', 'Content creation', 'https://httpbin.org/post', 'POST', 'none', '{"type":"object","properties":{"title":{"type":"string"},"category":{"type":"string"}},"required":["title"]}', '{}', '{content}', 'writing', false, 'low', true, 1),
('00000000-0000-0000-0000-000000000030', '11111111-1111-4111-8111-111111111111', 'publish_draft', 'Publish a draft', 'Publication', 'https://httpbin.org/post', 'POST', 'none', '{"type":"object","properties":{"draft_id":{"type":"string"}},"required":["draft_id"]}', '{}', '{content}', 'publishing', true, 'high', true, 1);
