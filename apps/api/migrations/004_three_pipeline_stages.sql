-- Do not silently reclassify or hide existing business records.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM crm.deals WHERE stage NOT IN ('new', 'contacted', 'won')) THEN
        RAISE EXCEPTION 'Pipeline reduction requires explicit classification of legacy stages before migration';
    END IF;
END $$;
ALTER TABLE crm.deals DROP CONSTRAINT deals_stage_check;
ALTER TABLE crm.deals ADD CONSTRAINT deals_stage_check CHECK (stage IN ('new','contacted','won'));
