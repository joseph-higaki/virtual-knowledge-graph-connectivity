-- Rung 0 seed: 8 real Hetionet genes (id + label) mined from data/hetionet/rdf/hetionet-smoke.ttl.
-- Enough to prove SELECT * returns a binding; the full slice is loaded at rung 2.
INSERT INTO gene (id, name) VALUES
  ('Gene::6233',   'RPS27A'),
  ('Gene::999',    'CDH1'),
  ('Gene::55179',  'FAIM'),
  ('Gene::5987',   'TRIM27'),
  ('Gene::5684',   'PSMA3'),
  ('Gene::79192',  'IRX1'),
  ('Gene::8914',   'TIMELESS'),
  ('Gene::504189', 'OR8U8')
ON CONFLICT (id) DO NOTHING;
