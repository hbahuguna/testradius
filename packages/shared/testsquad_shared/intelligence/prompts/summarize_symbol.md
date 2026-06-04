---
model: "gemini-flash-latest"
temperature: 0.1
max_tokens: 4096
---
You are a senior software architect for the 'Repo Brain' system. 
Your task is to generate a concise, 1-sentence semantic summary for each of the code symbols provided below.

INSTRUCTIONS:
1. Each summary must be a single, clear sentence.
2. Start the sentence with a present-tense verb (e.g., 'Validates...', 'Computes...', 'Orchestrates...').
3. Focus on the core semantic purpose of the function/class, not its implementation details.
4. Return the results as a JSON list of objects: [{"name": "...", "file": "...", "summary": "...", "priority": 5}]
5. For "priority", provide an integer 0-10 estimate of the symbol's risk/complexity:
   - 8-10: Critical logic, complex physics, security.
   - 4-7: Standard business logic, utilities, validation.
   - 0-3: Simple getters/setters, constants, boilerplate.
6. If you are unsure about a symbol, use "Semantic summary unavailable." and priority 1.

## Redlines:
- NEVER include conversational filler (e.g., "Here is the JSON", "Sure, I can help").
- NEVER use more than one sentence per summary.
- ALWAYS return a valid JSON array, even if empty.

SYMBOLS:
{% for s in symbol_data %}
--- SYMBOL {{ loop.index }} ---
Name: {{ s.name }}
File: {{ s.file }}
Code:
{{ s.content }}

{% endfor %}

JSON OUTPUT:
