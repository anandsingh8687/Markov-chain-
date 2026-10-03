Two attempts have worked on the issue below and have now stopped. Your only job is to put the chosen patch in and submit it. Do exactly this, nothing else:

1. Call the run_command tool with command: python3 .swetools/pick_patch.py --finisher
   (only if that says No such file: call the run_skill_script tool with skill_name = swe-tools-fin and file_path = scripts/pick_patch.py)
2. If its output starts with FINAL PATCH IS IN /workspace: call the submit_patch tool, then reply with one short line.
   If its output starts with NOT FINAL: reply with one short line and call no tool.

Do not investigate, view or edit anything, and do not load any skill.

# The issue (for reference only)
{problem_description}

# Reports
Attempt A: {attempt_a_report?}
Attempt B: {attempt_b_report?}
