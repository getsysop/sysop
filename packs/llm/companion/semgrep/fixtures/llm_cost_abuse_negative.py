from google.genai import types

# ok: llm-cost-abuse — max_output_tokens present
types.GenerateContentConfig(max_output_tokens=2048)

# ok: llm-cost-abuse — max_output_tokens present with other kwargs
types.GenerateContentConfig(temperature=0.1, max_output_tokens=4096)

# ok: llm-cost-abuse — type annotation, not a constructor call
def foo(config: types.GenerateContentConfig) -> None:
    pass
