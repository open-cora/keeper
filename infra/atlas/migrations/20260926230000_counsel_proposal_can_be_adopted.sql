-- A proposal gains a second way to stop being open, and the row has to say which.
--
-- Until now one thing could close a proposal: a step somewhere ran what it
-- proposed, and somebody reported that afterwards. Adoption is the other way,
-- and it is a different fact. This system chose the proposal, chose a beamline
-- and the devices it may touch, and dispatched work for it, all in one
-- transaction with this row's update.
--
-- `execution_id` alone cannot tell them apart, because both set it. So the
-- read side derives the three states from two nullable timestamps, which is
-- the shape `proj_counsel_inquiry_summary` next door already uses:
--
--     Open      execution_id is null
--     Adopted   adopted_at is set
--     Taken     taken_at is set
--
-- No status column, for the reason this context has refused one twice before:
-- a word beside the timestamps would be the same fact written twice, and two
-- spellings are two things a projection can write inconsistently.
--
-- Additive, so the table is altered rather than dropped and rebuilt. Every row
-- that exists was written by the take arm and its `adopted_at` is correctly
-- null, which is what makes this the one change to this projection that does
-- not need a replay.

ALTER TABLE proj_counsel_proposal_summary
    ADD COLUMN adopted_at timestamptz;

-- No index. The open lookup is still the null test on `execution_id`, and
-- nothing yet asks which of the two closed a proposal: an agent holds the ids
-- of its own, and an operator asking what nobody acted on is asking the open
-- question the existing partial index already serves. An index maintained for
-- nobody is a write cost with no reader.
