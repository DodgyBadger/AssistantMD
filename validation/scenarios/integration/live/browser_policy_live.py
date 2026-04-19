"""
Integration scenario that contracts browser policy branches and routing behavior.

Uses deterministic inputs so browser policy enforcement does not depend on third-
party pages or flaky network behavior.
"""

import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


LOCAL_BLOCK_URL = "http://127.0.0.1/browser-policy-check"
SELECTOR_PAGE_URL = (
    "data:text/html,"
    + quote(
        (
            "<html><head><title>Selector Policy</title></head><body><main>"
            "<h1>Selector Policy</h1><p>Primary content for selector guidance.</p>"
            "</main></body></html>"
        ),
        safe="",
    )
)
LARGE_PAGE_URL = (
    "data:text/html,"
    + quote(
        (
            "<html><head><title>Browser Routing</title></head><body><main><h1>"
            "Browser Routing</h1><p>"
            + ("Browser routing validation content. " * 400)
            + "</p></main></body></html>"
        ),
        safe="",
    )
)


class BrowserPolicyScenario(BaseScenario):
    """Validate browser policy blocks and current large-output behavior."""

    async def test_scenario(self):
        vault = self.create_vault("BrowserPolicyVault")
        self.create_file(vault, "AssistantMD/Workflows/browser_policy.md", WORKFLOW_CONTENT)

        checkpoint = self.event_checkpoint()
        await self.start_system()

        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "BrowserPolicyVault/browser_policy"},
        )

        update_setting = self.call_api(
            "/api/system/settings/general/auto_cache_max_tokens",
            method="PUT",
            data={"value": "100"},
        )
        assert update_setting.status_code == 200, "Scenario should lower auto-buffer threshold"

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "browser_policy")
        assert result.status == "completed", "Browser policy workflow should complete"
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="browser_navigation_failed",
            expected={"tool": "browser", "result_type": "blocked", "url": LOCAL_BLOCK_URL},
        )
        self.assert_event_contains(
            events,
            name="browser_navigation_failed",
            expected={"tool": "browser", "result_type": "selector_not_found"},
        )
        routed_events = self.find_events(events, name="tool_output_routed", tool="browser")
        self.soft_assert_equal(
            len(routed_events),
            0,
            "Browser workflow output should remain inline; hidden tool routing is chat-only now",
        )

        blocked_output = (vault / "tool-outputs" / "blocked.md").read_text(encoding="utf-8")
        assert blocked_output.strip(), "Blocked URL step should still produce an output file"

        selector_output = (vault / "tool-outputs" / "selector.md").read_text(encoding="utf-8")
        assert selector_output.strip(), "Selector guidance step should still produce an output file"

        routed_output = (vault / "tool-outputs" / "routed.md").read_text(encoding="utf-8")
        assert routed_output.strip(), "Routing step should still produce a response file"

        await self.stop_system()
        self.teardown_scenario()


WORKFLOW_CONTENT = f"""---
workflow_engine: step
enabled: false
description: Validation workflow for browser policy handling
---

## BLOCK_LOCAL
@model gpt-mini
@tools browser
@output file: tool-outputs/blocked

Call browser on this exact URL: {LOCAL_BLOCK_URL}
Then report the tool result briefly. You must call the browser tool before responding.

## SELECTOR_GUIDANCE
@model gpt-mini
@tools browser
@output file: tool-outputs/selector

Call browser on this exact URL with wait_for_selector set to `aside`: {SELECTOR_PAGE_URL}
Then report the tool result briefly. You must call the browser tool before responding.

## AUTO_BUFFER
@model gpt-mini
@tools browser
@output file: tool-outputs/routed

Call browser on this exact URL and do not set any selectors: {LARGE_PAGE_URL}
Then report where the large browser output was routed. You must call the browser tool before responding.
"""
