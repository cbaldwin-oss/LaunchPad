-- ============================================================================
-- sync/add_draft_columns.sql
--
-- Adds review-before-publish staging to BackEndData for every ALREADY
-- UNIFIED project (unified_schedule = true in launchpad_projects). Once a
-- project's Bridge and Scheduler share one table (see
-- sync/unify_backend_schedule.sql), Bridge's own push/pull layer has
-- nothing left to gate — an edit in Bridge IS the row Scheduler reads,
-- instantly. These two columns give Bridge somewhere to stage a pending
-- edit/move/delete without touching what Scheduler actually sees, so the
-- Accept/Discard workflow (bridge-view.js: markPendingSync/markPendingDelete,
-- acceptPendingChanges/discardPendingChanges) keeps working under the
-- single-table model instead of silently doing nothing.
--
-- SAFETY: purely additive — two new nullable/defaulted columns, no existing
-- column touched, no row altered. Scheduler's own code (index.html:
-- applyScheduleDataToDom(), saveRow()) never references either column, so
-- it keeps working completely unmodified.
--
--   draft         jsonb   — the full proposed field set (same shape
--                           bridge-view.js's itemToBackEndRow() already
--                           produces, minus id) when an edit/move is
--                           pending; null the rest of the time.
--   draft_deleted boolean — true while a delete is pending (Bridge has
--                           already stopped showing the item locally, but
--                           the row itself — and everything Scheduler
--                           reads from it — stays untouched until Accept).
-- ============================================================================

do $$
declare
    proj record;
begin
    for proj in select table_prefix from launchpad_projects where unified_schedule loop
        execute format(
            'alter table %I
                add column if not exists draft jsonb,
                add column if not exists draft_deleted boolean not null default false',
            proj.table_prefix || 'BackEndData'
        );
    end loop;
end $$;
