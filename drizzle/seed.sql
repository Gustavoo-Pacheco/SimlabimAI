-- Seed example songs. Edit freely before running.
-- Re-runnable: ON CONFLICT keeps existing rows.
INSERT INTO songs (slug, title, author, created_at) VALUES
  ('meteoro',          'Meteoro',           'paralamas-do-sucesso', (EXTRACT(EPOCH FROM now()) * 1000)::bigint),
  ('palacios',         'Palácios',          'unknown',              (EXTRACT(EPOCH FROM now()) * 1000)::bigint),
  ('garota-de-ipanema','Garota de Ipanema', 'tom-jobim',            (EXTRACT(EPOCH FROM now()) * 1000)::bigint),
  ('asa-branca',       'Asa Branca',        'luiz-gonzaga',         (EXTRACT(EPOCH FROM now()) * 1000)::bigint),
  ('aquarela',         'Aquarela',          'toquinho',             (EXTRACT(EPOCH FROM now()) * 1000)::bigint)
ON CONFLICT (slug) DO NOTHING;
