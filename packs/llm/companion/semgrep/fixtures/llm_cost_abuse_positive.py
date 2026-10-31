from google.genai import types

# ruleid: llm-cost-abuse
types.GenerateContentConfig(temperature=0.1)

# ruleid: llm-cost-abuse
types.GenerateContentConfig()

# ruleid: llm-cost-abuse
GenerateContentConfig(temperature=0.1)

# ruleid: llm-cost-abuse — present, but None is no bound
types.GenerateContentConfig(max_output_tokens=None)

# ruleid: llm-cost-abuse — None among other kwargs
types.GenerateContentConfig(temperature=0.1, max_output_tokens=None)

# ruleid: llm-cost-abuse — the bare-name constructor, None
GenerateContentConfig(max_output_tokens=None)
