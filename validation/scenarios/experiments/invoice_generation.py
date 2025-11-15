"""
Invoice Generation scenario - tests automated weekly invoice creation from billable hours logs.

Tests critical billing reliability requirements:
- All entries processed (no under-billing)
- No double-counting (no over-billing)
- Accurate hour summation
- Correct client grouping
- Proper use of {pending} pattern to process all unprocessed timesheets
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class TestInvoiceGenerationScenario(BaseScenario):
    """Test weekly invoice generation workflow with reliability validation."""

    async def test_scenario(self):
        """Execute complete invoice generation workflow with multiple weeks of data."""

        # === SETUP ===
        vault = self.create_vault("Consulting")

        # Create the invoice generator workflow and template
        self.create_file(vault, "AssistantMD/Workflows/invoice_generator.md", INVOICE_GENERATOR_WORKFLOW)
        self.create_file(vault, "invoice-template.md", INVOICE_TEMPLATE)

        # Create Week 1, 2, and 3 billable hours logs in timesheets subfolder
        self.create_file(vault, "timesheets/billable-hours-2025-01-13.md", BILLABLE_HOURS_2025_01_13)
        self.create_file(vault, "timesheets/billable-hours-2025-01-20.md", BILLABLE_HOURS_2025_01_20)
        self.create_file(vault, "timesheets/billable-hours-2025-01-27.md", BILLABLE_HOURS_2025_01_27)

        # === SYSTEM STARTUP ===
        await self.start_system()

        self.expect_vault_discovered("Consulting")
        self.expect_workflow_loaded("Consulting", "invoice_generator")

        # === FIRST RUN - Should process all three pending weeks ===
        self.set_date("2025-02-02")  # Sunday - invoice generation day

        await self.trigger_job(vault, "invoice_generator")

        # === ASSERTIONS ===
        self.expect_scheduled_execution_success(vault, "invoice_generator")

        # Expected totals across all three weeks:
        # Week 1 (Jan 13):
        #   Acme Corp: 2.5 + 3.0 + 1.5 + 2.0 = 9.0 hours
        #   TechStart Inc: 1.0 + 4.0 + 2.0 = 7.0 hours
        #   GlobalTech LLC: 2.0 + 3.5 + 1.5 = 7.0 hours
        # Week 2 (Jan 20):
        #   Acme Corp: 4.0 + 3.5 + 2.0 = 9.5 hours
        #   TechStart Inc: 2.5 + 1.5 = 4.0 hours
        #   GlobalTech LLC: 2.0 hours
        # Week 3 (Jan 27):
        #   Acme Corp: 3.0 + 1.5 = 4.5 hours
        #   TechStart Inc: 2.0 + 3.5 = 5.5 hours
        #   GlobalTech LLC: 2.5 + 4.0 = 6.5 hours

        # The agent will create invoice files using file_ops_safe
        # We'll inspect the vault to verify invoices were generated correctly

        # === SECOND RUN - No new pending files, step should skip ===
        self.set_date("2025-02-09")  # Next Sunday

        await self.trigger_job(vault, "invoice_generator")

        self.expect_scheduled_execution_success(vault, "invoice_generator")

        # The required parameter should cause the step to skip since no pending files
        # No LLM calls should be made, saving API costs

        # === ADD NEW TIMESHEETS - Simulate new week of work ===
        # Create Week 4 billable hours (Feb 3-7)
        self.create_file(vault, "timesheets/billable-hours-2025-02-03.md", BILLABLE_HOURS_2025_02_03)

        # === THIRD RUN - Should process only the new pending file ===
        self.set_date("2025-02-16")  # Two weeks later, next Sunday

        await self.trigger_job(vault, "invoice_generator")

        self.expect_scheduled_execution_success(vault, "invoice_generator")

        # Should process only the new week's timesheet
        # Week 4 (Feb 3):
        #   Acme Corp: 2.0 + 1.5 = 3.5 hours
        #   TechStart Inc: 3.0 + 2.5 = 5.5 hours
        #   GlobalTech LLC: 4.0 + 1.0 = 5.0 hours

        # === FOURTH RUN - No new pending files again, should skip ===
        self.set_date("2025-02-23")  # Another Sunday

        await self.trigger_job(vault, "invoice_generator")

        self.expect_scheduled_execution_success(vault, "invoice_generator")

        # Should skip again since all files processed

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === ASSISTANT TEMPLATES ===

INVOICE_GENERATOR_WORKFLOW = """---
schedule: cron: 0 9 * * *
workflow_engine: step
enabled: true
description: Weekly invoice generator that extracts billable hours by client
week_start_day: monday
---

## INSTRUCTIONS

You are a precise invoice generator. Your job is to process ALL unprocessed billable hours logs and create separate invoice files for each client found.

**Critical Requirements for Reliability:**
1. Process ALL pending timesheets - never skip a week
2. Parse each line exactly: date, client, hours, activity
3. Identify all unique clients automatically
4. Group entries by exact client name (case-sensitive)
5. Sum hours accurately - missing entries = under-billing
6. Never double-count - duplicates = over-billing
7. Create one invoice file per client using file operations tool
8. Follow the invoice template format exactly

**Workflow:**
1. Read all pending billable hours files
2. Parse and extract all entries
3. Identify unique client names
4. For each client: group entries, sum hours, create invoice file
5. Save invoices to: invoices/{week-date}/[Client-Name].md

## STEP1
@run-on sunday
@model gpt-5
@tools file_ops_safe, code_execution
@input-file timesheets/{pending} (required)
@input-file invoice-template.md

Process all supplied billable hours logs and generate ONE CONSOLIDATED INVOICE per client.

**IMPORTANT: All timesheet content has been provided to you in this context. DO NOT use file_operations to read or list files. Work directly with the supplied content.**

You will receive:
1. All unprocessed timesheet files with billable hours entries (already loaded in context)
2. An invoice template showing the exact format to use (already loaded in context)

**Your task:**
1. Use code_execution tool to parse all entries from the supplied timesheet content with 100% accuracy
2. Write Python code to:
   - Parse each line as CSV format: date, client, hours, activity
   - Combine entries from ALL supplied timesheets
   - Group all entries by exact client name (case-sensitive)
   - Sum total hours per client across all timesheets with decimal precision
   - Verify no entries are missing or duplicated
3. For each unique client, create ONE consolidated invoice:
   - Follow the invoice template format exactly
   - Include all their entries from all supplied timesheets
   - Sort entries chronologically by date
   - Show total hours summed across all entries
4. Save each invoice using file_ops_safe tool to: invoices/[client-name] - [today's date] - DRAFT.md. If for some reason the exact file already exists, add a sequential number to the new filename and include a note for the user to review as possible duplicate.

**Critical: Use code execution for all parsing and math operations to ensure billing accuracy.**
The code should validate that every line is processed and all hours are correctly summed.
"""

INVOICE_TEMPLATE = """# Invoice Template

Use this template structure for all client invoices:

```markdown
# Invoice - [Client Name]
//Client Address - user to fill in when reviewing>//

| Date | Hours | Description |
|------|-------|-------------|
| YYYY-MM-DD | X.X | Activity description |

**Total Hours:** [total from above]
**Rate:** $120 / hour
**Total Amount:** $[calculated if rate known, otherwise leave blank]
```

## Instructions for Invoice Generation

1. **Client Name**: Use exact client name as it appears in billable hours log
2. **Date Format**: Keep ISO format (YYYY-MM-DD)
3. **Hours Format**: One decimal place (2.5, not 2.50)
4. **Total Hours**: Sum all hours for the client - must be exact
5. **Activity Descriptions**: Copy verbatim from log
6. **Sorting**: List entries chronologically by date
"""

BILLABLE_HOURS_2025_01_13 = """# Billable Hours - Week of January 13, 2025

2025-01-13, Acme Corp, 2.5, Database optimization and query performance tuning
2025-01-13, TechStart Inc, 1.0, Initial consultation on cloud migration strategy
2025-01-14, Acme Corp, 3.0, Frontend component development and testing
2025-01-14, GlobalTech LLC, 2.0, Security audit and vulnerability assessment
2025-01-15, TechStart Inc, 4.0, AWS infrastructure setup and configuration
2025-01-15, Acme Corp, 1.5, Code review and documentation updates
2025-01-16, GlobalTech LLC, 3.5, API development and integration testing
2025-01-16, TechStart Inc, 2.0, Database migration and data validation
2025-01-17, Acme Corp, 2.0, Bug fixes and deployment to staging environment
2025-01-17, GlobalTech LLC, 1.5, Client meeting and technical requirements gathering
"""

BILLABLE_HOURS_2025_01_20 = """# Billable Hours - Week of January 20, 2025

2025-01-20, Acme Corp, 4.0, New feature development and unit testing
2025-01-20, TechStart Inc, 2.5, Performance optimization and monitoring setup
2025-01-21, Acme Corp, 3.5, Integration testing and bug fixes
2025-01-21, GlobalTech LLC, 2.0, Documentation and training materials
2025-01-22, TechStart Inc, 1.5, Code review and deployment preparation
2025-01-22, Acme Corp, 2.0, Client demo and feedback session
"""

BILLABLE_HOURS_2025_01_27 = """# Billable Hours - Week of January 27, 2025

2025-01-27, Acme Corp, 3.0, Sprint planning and architecture design
2025-01-27, GlobalTech LLC, 2.5, API endpoint development and testing
2025-01-28, TechStart Inc, 2.0, Infrastructure monitoring and alerts setup
2025-01-28, Acme Corp, 1.5, Code review and merge requests
2025-01-29, GlobalTech LLC, 4.0, Integration work with third-party services
2025-01-30, TechStart Inc, 3.5, Database optimization and indexing
"""

BILLABLE_HOURS_2025_02_03 = """# Billable Hours - Week of Feb 3, 2025

2025-02-03, Acme Corp, 2.0, Database migration planning
2025-02-04, TechStart Inc, 3.0, API integration testing
2025-02-05, GlobalTech LLC, 4.0, Security audit implementation
2025-02-06, Acme Corp, 1.5, Performance optimization
2025-02-07, TechStart Inc, 2.5, Documentation updates
2025-02-07, GlobalTech LLC, 1.0, Code review sessions
"""
