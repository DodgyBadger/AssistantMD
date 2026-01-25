from typing import AsyncIterator, Optional, List, Any
import json
from datetime import datetime

from pydantic_ai.agent import Agent
from core.constants import DEFAULT_TOOL_RETRIES
from core.directives.model import ModelDirective
from core.settings.store import get_general_settings

async def create_agent(
    model=None,
    tools: Optional[List] = None,
    retries: Optional[int] = None,
    output_type: Optional[Any] = None,
    history_processors: Optional[List] = None,
) -> Agent:
    """Create agent by composing pre-configured components following Pydantic AI patterns.

    Pure composition function that assembles pre-configured model and tools into a Pydantic AI Agent.

    Args:
        model: Pre-configured Pydantic AI model instance, or None to use default model
        tools: Optional list of tool functions (extracted from BaseTool classes by directives)
        retries: Number of retries for tool validation errors (defaults to DEFAULT_TOOL_RETRIES)
        output_type: Optional structured output specification for the agent
        history_processors: Optional list of history processors to apply

    Returns:
        Configured Pydantic AI Agent ready for use
    """
    
    # Handle default model if none provided
    if model is None:
        general_settings = get_general_settings()
        default_model_entry = general_settings.get("default_model")
        default_model_value = default_model_entry.value if default_model_entry else None
        if not default_model_value:
            raise ValueError(
                "Set 'default_model' in system/settings.yaml before creating agents without an explicit model."
            )

        default_model_name = str(default_model_value).lower().strip()

        # Create model instance using directive processor
        model_directive = ModelDirective()
        model = model_directive.process_value(default_model_name, '/default')
    
    # Pure composition - assemble the pre-configured pieces
    agent_kwargs = {
        'model': model,
        'retries': retries if retries is not None else DEFAULT_TOOL_RETRIES
    }
    if history_processors:
        agent_kwargs['history_processors'] = history_processors
    if tools:
        agent_kwargs['tools'] = tools
    if output_type is not None:
        agent_kwargs['output_type'] = output_type

    agent = Agent(**agent_kwargs)

    agent.instructions(lambda _: f"The current date is {datetime.today().strftime('%A, %B %d, %Y')}.")

    return agent


async def generate_stream(agent, prompt, message_history) -> AsyncIterator[str]:
    try:
        async with agent.run_stream(
            prompt,
            message_history=message_history
        ) as result:
            full_response = ""
            async for text in result.stream_text():
                delta_text = text[len(full_response):]
                full_response = text
                
                chunk = {
                    "choices": [{
                        "delta": {
                            "content": delta_text
                        },
                        "index": 0,
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            
            yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
            
    except Exception:
        raise


async def generate_response(agent, prompt, message_history=None):
    try:
        if message_history:
            result = await agent.run(
                prompt,
                message_history=message_history
            )
        else:
            result = await agent.run(prompt)
            
        return result.output

    except Exception:
        raise
