"""Gemini client helper — shared across all agents."""

from __future__ import annotations

import os
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()


def get_model_name() -> str:
    """Return the model name from env, defaulting to gemini-2.5-flash."""
    return os.getenv("MODEL", "gemini-2.5-flash")


def get_api_key() -> str:
    """Return the Gemini API key from env."""
    key = os.getenv("GEMINI_API_KEY", "")
    placeholders = {"your_new_key_here", "your_gemini_key_here", "AIza...", ""}
    if key in placeholders:
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
    dispatch_fn: Callable[[str, dict], str],
    max_iterations: int = 20,
    stop_check: Callable[[], bool] | None = None,
) -> str:
    """
    Generic Gemini function-calling agent loop.

    Args:
        client: genai.Client instance
        model: model name string
        system_prompt: system instruction text
        tools_config: list of dicts with 'name', 'description', 'parameters'
        initial_message: user prompt text
        dispatch_fn: callable(tool_name, tool_args_dict) -> str result
        max_iterations: max number of API round-trips
        stop_check: optional callable() -> bool; if it returns True the loop exits early

    Returns the last text response from the model (may be empty if it only called tools).
    """
    from google.genai import types

    # Build tool declarations
    tool_declarations = []
    for t in tools_config:
        params = t.get("parameters", {})
        tool_declarations.append(
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=params if params else None,
            )
        )

    gemini_tools = [types.Tool(function_declarations=tool_declarations)]

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=gemini_tools,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
    )

    contents = [types.Content(role="user", parts=[types.Part(text=initial_message)])]

    final_text = ""

    for _i in range(max_iterations):
        # Early exit if external state says we're done
        if stop_check and stop_check():
            break

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        if not response.candidates:
            break

        candidate = response.candidates[0]

        # Safety check on content
        if not candidate.content or not candidate.content.parts:
            break

        parts = candidate.content.parts

        # Collect text parts and function call parts.
        # IMPORTANT: In gemini-2.5-flash (thinking model), function calls can be
        # embedded inside parts that also have thought=True. We must check for
        # function_call on EVERY part, thought or not.
        text_parts = []
        fn_calls = []
        for p in parts:
            # Always extract function calls, even from thought parts
            fc = getattr(p, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                fn_calls.append(fc)
                continue  # this part is a tool call, not text

            # Skip pure thought/reasoning parts (no function call)
            if getattr(p, "thought", False) or getattr(p, "thought_signature", None):
                continue

            # Real text response
            if getattr(p, "text", None):
                text_parts.append(p.text)

        if text_parts:
            final_text = "\n".join(text_parts)

        # No function calls → model is done
        if not fn_calls:
            break

        # Add model response to conversation history
        contents.append(candidate.content)

        # Execute all function calls and collect results
        fn_response_parts = []
        for fc in fn_calls:
            try:
                result = dispatch_fn(fc.name, dict(fc.args) if fc.args else {})
            except Exception as exc:
                result = f"ERROR executing {fc.name}: {exc}"

            fn_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": str(result)},
                    )
                )
            )

            # Check stop condition after each tool call
            if stop_check and stop_check():
                break

        contents.append(types.Content(role="user", parts=fn_response_parts))

        # Check finish reason
        finish = getattr(candidate, "finish_reason", None)
        if finish and hasattr(finish, "name") and finish.name == "STOP":
            break

    return final_text
