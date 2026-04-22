"""AssistantMD-owned Pydantic AI capability helpers.

Import concrete builders from their modules directly. This package initializer
intentionally avoids eager re-exports because some capability modules depend on
authoring context code that is not safe to import during authoring bootstrap.
"""
