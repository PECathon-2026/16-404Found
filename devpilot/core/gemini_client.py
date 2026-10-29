"""Gemini client helper — shared across all agents."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def get_model_name() -> str:
    """Return the model name from env, defaulting to gemini-2.0-flash."""
    return os.getenv("MODEL", "gemini-2.0-flash")


def get_api_key() -> str:
    """Return the Gemini API key from env."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "your_new_key_here" or key == "your_gemini_key_here":
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Edit devpilot/.env and paste your key from https://aistudio.google.com"
        )
    return key


def make_client():
    """Return a configured google.genai Client."""
    from google import genai
    return genai.Client(api_key=get_api_key())


def run_agent_loop(
    client,
    model: str,
    system_prompt: str,
    tools_config: list[dict],
    initial_message: str,
    dispatch_fn,
    max_iterations: int = 20,
) -> str:
    """
    Generic Gemini tool-use agent loop.

    - client: genai.Client
    - model: model name string
    - system_prompt: system instruction text
    - tools_config: list of tool dicts with 'name', 'description', 'parameters'
    - initial_message: user prompt text
    - dispatch_fn: callable(tool_name, tool_args) -> str
    - max_iterations: max number of API calls

    Returns the final text from the model.
    """
    from google.genai import types

    # Build tool declarations
    tool_declarations = []
    for t in tools_config:
        tool_declarations.append(
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t.get("parameters", {}),
            )
        )

    gemini_tools = [types.Tool(function_declarations=tool_declarations)]

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=gemini_tools,
    )

    contents = [types.Content(role="user", parts=[types.Part(text=initial_message)])]

    final_text = ""

    for _i in range(max_iterations):
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts

        # Collect text and function calls
        text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
        fn_calls = [p.function_call for p in parts if hasattr(p, "function_call") and p.function_call]

        if text_parts:
            final_text = "\n".join(text_parts)

        # No function calls → done
        if not fn_calls:
            break

        # Add model response to history
        contents.append(candidate.content)

        # Execute function calls and collect responses
        fn_response_parts = []
        for fc in fn_calls:
            result = dispatch_fn(fc.name, dict(fc.args))
            fn_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": str(result)},
                    )
                )
            )

        contents.append(types.Content(role="user", parts=fn_response_parts))

        # Check finish reason
        if candidate.finish_reason and candidate.finish_reason.name == "STOP":
            break

    return final_text
