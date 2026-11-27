# Local and interchangeable AI providers

JARVIS defaults to Groq because its current FastAgent tool loop depends on reliable
function calling. Provider selection is independent of speech recognition and TTS.

## Configure or switch providers

Run \`jarvis-setup ai\` at any time, then restart JARVIS:

- **Groq** — full tool-calling agent and default.
- **OmniRoute** — the existing local gateway for primary chat (tool actions remain with Groq).\n- **Local AI** — any OpenAI-compatible local endpoint, including Ollama at
  \`http://127.0.0.1:11434/v1\`.
- **Custom AI** — any reachable OpenAI-compatible endpoint and model.

Local and custom endpoints are text-only by default. Device actions continue through
Groq unless the selected endpoint's tool calling is explicitly enabled. Do not enable
tool calling for a model that has not been verified to return valid function calls.
LFM2.5 350M is intended for lightweight chat, not reliable tool execution.

## LFM2.5 350M with Ollama

The repository includes \`Modelfile.lfm2.5-350m\`. Create the Ollama model with:

\`\`\`bash
ollama create jarvis-lfm -f Modelfile.lfm2.5-350m
\`\`\`

Then select Local AI with model \`jarvis-lfm\` using \`jarvis-setup ai\`.

Setup stores endpoint, model, provider selection, and any API key in the private
\`.env\` file. It does not download model weights automatically. Pull/install the
model separately and verify that Ollama is running.

## Context retention

The dispatcher already supplies recent conversation history and relevant persistent
JARVIS memory. For small local models, the provider adapter packs that into bounded
context: relevant memory, the latest conversation turns, and the current request.
This avoids burying the live question in a long transcript. It does not increase the
model's reasoning capacity; a 350M model can still miss implications or references.
For important long-term facts, use JARVIS memory rather than relying on raw context.

## Environment variables

- \`JARVIS_AI_PROVIDER=groq|local|custom\`
- \`JARVIS_AI_FALLBACK_PROVIDER=none|local\`
- \`JARVIS_LOCAL_AI_BASE_URL\`, \`JARVIS_LOCAL_AI_API_KEY\`, \`JARVIS_LOCAL_AI_MODEL\`
- \`JARVIS_CUSTOM_AI_BASE_URL\`, \`JARVIS_CUSTOM_AI_API_KEY\`, \`JARVIS_CUSTOM_AI_MODEL\`
- \`JARVIS_LOCAL_AI_TOOL_CALLING=0|1\`
- \`JARVIS_CUSTOM_AI_TOOL_CALLING=0|1\`

Groq-to-local fallback is only used before any action has run. JARVIS never retries an
action through another model after a tool has already executed.
