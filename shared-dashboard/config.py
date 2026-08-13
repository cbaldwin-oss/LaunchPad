PROJECT_TYPE = "data_center"
BRAND_NAME = "CriticalArc"
BRAND_COLOR = "#39B54A"

ISSUE_STATUSES = ["Open", "In Progress", "Pending Verification", "Closed", "Void"]
CHECKLIST_VERIFIED = ["Finished", "GC to Verify"]
checklist_complete_statuses = ["Finished"]

CHECKLIST_PIPELINE = [
    ("Not Started", "not_started_date"),
    ("In Progress", "in_progress_date"),
    ("GC to Verify", "gc_to_verify_date"),
    ("Finished", "finished_date"),
]