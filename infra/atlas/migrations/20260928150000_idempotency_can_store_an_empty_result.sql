-- An idempotency row learns to say "succeeded, and there was nothing to return".
--
-- The three states of a row were inferred from which column was null, which
-- made one of them unrepresentable. `result IS NULL` had to mean "no result
-- yet", so it could not also mean "a result that is null", and a handler
-- returning nothing had no legal row to land in:
--
--     in flight   locked_at set,   result null,     error null
--     succeeded   locked_at null,  result NOT null, error null
--     failed      locked_at null,  result null,     error set
--
-- What that cost is not theoretical. The application-side wrapper cannot wrap
-- a handler that returns nothing: against this constraint the finalize raises
-- a check violation AFTER the handler has already appended its events, so the
-- caller sees a 500 for a write that succeeded. The in-memory twin has no
-- constraint to violate and loses the row instead, reading the replay as a
-- fresh claim and running the handler a second time. One defect, two
-- symptoms, and the less alarming one is the one that shows up in tests.
--
-- So the state stops being inferred and becomes a column. `outcome` is null
-- while the row is in flight and one of two words once it is not, and the
-- succeeded arm below says nothing at all about `result`. That is the whole
-- change: a null result is now a result.
--
-- The words are 'succeeded' and 'failed', lowercase, and both adapters import
-- them from `keeper.infrastructure.ports.idempotency_store` rather than
-- spelling them again. Lowercase rather than the PascalCase this project's
-- domain enums use, because those are chosen so a response body reads without
-- a mapping step and these never reach one.
--
-- Additive for every row that exists, so the table is altered rather than
-- rebuilt. The backfill below can reconstruct the outcome of every existing
-- row exactly, because the old constraint guaranteed the three states were
-- distinguishable: that is what made the old encoding sound for every result
-- except the null one.

ALTER TABLE idempotency_keys
    ADD COLUMN outcome text;

-- Every completed row, classified by the encoding that was true when it was
-- written. An in-flight row keeps a null outcome, which is the first arm of
-- the new constraint and the state it is already in.
UPDATE idempotency_keys
SET outcome = CASE
        WHEN error_type IS NOT NULL THEN 'failed'
        WHEN locked_at IS NULL THEN 'succeeded'
    END;

-- Dropped and re-added rather than edited, because Postgres has no ALTER for
-- a check constraint's expression. The replacement is in this same file and
-- covers the same three states, so no guarantee is removed: the succeeded arm
-- is widened by exactly the null result it used to refuse, and every other
-- combination is still rejected.
ALTER TABLE idempotency_keys
    DROP CONSTRAINT idempotency_keys_state_chk;

ALTER TABLE idempotency_keys
    ADD CONSTRAINT idempotency_keys_state_chk CHECK (
        (
            locked_at IS NOT NULL
            AND outcome IS NULL
            AND result IS NULL
            AND error_type IS NULL
            AND error_msg IS NULL
        )
        OR (
            locked_at IS NULL
            AND outcome = 'succeeded'
            AND error_type IS NULL
            AND error_msg IS NULL
        )
        OR (
            locked_at IS NULL
            AND outcome = 'failed'
            AND result IS NULL
            AND error_type IS NOT NULL
            AND error_msg IS NOT NULL
        )
    );

-- No GRANT. They are table-level and already cover this column, and no index
-- either: `outcome` is read only on a row already found by the primary key.
