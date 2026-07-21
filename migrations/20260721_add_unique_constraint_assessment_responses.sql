-- Check for duplicate responses before enforcing one row per
-- (assessment_id, question_definition_id) in kpmg_sar.assessment_responses.
SELECT
    assessment_id,
    question_definition_id,
    COUNT(*) AS duplicate_count
FROM kpmg_sar.assessment_responses
GROUP BY assessment_id, question_definition_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, assessment_id, question_definition_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM kpmg_sar.assessment_responses
        GROUP BY assessment_id, question_definition_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE NOTICE
            'Skipped uq_assessment_responses_assessment_question: duplicate assessment responses exist.';
    ELSIF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'kpmg_sar'
          AND table_name = 'assessment_responses'
          AND constraint_name = 'uq_assessment_responses_assessment_question'
          AND constraint_type = 'UNIQUE'
    ) THEN
        RAISE NOTICE
            'Constraint uq_assessment_responses_assessment_question already exists on kpmg_sar.assessment_responses.';
    ELSE
        ALTER TABLE kpmg_sar.assessment_responses
        ADD CONSTRAINT uq_assessment_responses_assessment_question
        UNIQUE (assessment_id, question_definition_id);

        RAISE NOTICE
            'Added uq_assessment_responses_assessment_question to kpmg_sar.assessment_responses.';
    END IF;
END $$;
