// testradius OpenCode Plugin
// SDET + TIA tools calling the local testradius HTTP server
// API docs: https://github.com/anthropics/claude-code/blob/main/docs/plugins.md

const API_BASE = "http://127.0.0.1:9800";

/** @type {import("@opencode-ai/plugin").Plugin} */
const plugin = {
  name: "testradius",
  tools: {
    // --- Page Proxy ---
    page_fetch: {
      name: "page_fetch",
      description: "Fetch a web page HTML. Downloads full HTML of the given URL so you can analyze interactive elements and build CSS selectors for tests.",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "The URL to fetch" },
        },
        required: ["url"],
      },
      execute: async ({ url }) => {
        const res = await fetch(`${API_BASE}/api/proxy/fetch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- DOM Analysis ---
    dom_analyze: {
      name: "dom_analyze",
      description: "Analyze HTML and return interactive elements (buttons, links, inputs) with CSS selectors. Call after page_fetch to understand what elements can be interacted with.",
      parameters: {
        type: "object",
        properties: {
          html: { type: "string", description: "Raw HTML to analyze" },
          url: { type: "string", description: "Original page URL (optional)" },
        },
        required: ["html"],
      },
      execute: async ({ html, url }) => {
        const res = await fetch(`${API_BASE}/api/dom/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ html, url: url || "" }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- TIA: Changed Files ---
    tia_get_changed_files: {
      name: "tia_get_changed_files",
      description: "List all files changed in the current branch vs main, plus diff length. Use to understand what code was modified before generating or selecting tests.",
      parameters: {
        type: "object",
        properties: {
          base: { type: "string", description: "Base branch (default: main)" },
        },
      },
      execute: async ({ base }) => {
        const res = await fetch(`${API_BASE}/api/tia/changed-files`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base: base || "main" }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- TIA: Full Impact Analysis ---
    tia_analyze_impact: {
      name: "tia_analyze_impact",
      description: "Full test impact analysis. Finds changed files vs main, then maps them to impacted test files. Returns structured impact report with changed files, impacted tests, and total count.",
      parameters: {
        type: "object",
        properties: {
          base: { type: "string", description: "Base branch (default: main)" },
        },
      },
      execute: async ({ base }) => {
        const res = await fetch(`${API_BASE}/api/tia/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base: base || "main" }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- Qwen SDET Inference ---
    sdet_qwen_infer: {
      name: "sdet_qwen_infer",
      description: "Call the fine-tuned Qwen3-8B SDET model for test generation suggestions, assertion selection, and test pattern recommendations. Returns model-generated text.",
      parameters: {
        type: "object",
        properties: {
          prompt: { type: "string", description: "Prompt to send to the SDET model" },
          max_tokens: { type: "number", description: "Max tokens in response (default: 512)" },
          temperature: { type: "number", description: "Sampling temperature (default: 0.7)" },
        },
        required: ["prompt"],
      },
      execute: async ({ prompt, max_tokens, temperature }) => {
        const res = await fetch(`${API_BASE}/api/qwen/infer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, max_tokens: max_tokens || 512, temperature: temperature || 0.7 }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- File Operations ---
    file_save: {
      name: "file_save",
      description: "Save generated test code to a file in the repository. Writes the file and creates parent directories if needed. Use after generating Playwright test code.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative file path in the repo" },
          content: { type: "string", description: "File content to write" },
        },
        required: ["path", "content"],
      },
      execute: async ({ path, content }) => {
        const res = await fetch(`${API_BASE}/api/files/save`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, content }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    file_read: {
      name: "file_read",
      description: "Read an existing file from the repository. Use to load existing test files for context before generating new ones.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative file path in the repo" },
        },
        required: ["path"],
      },
      execute: async ({ path }) => {
        const res = await fetch(`${API_BASE}/api/files/read`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    // --- Session Context ---
    sdet_session_init: {
      name: "sdet_session_init",
      description: "Initialize a new SDET session. Creates a session with an optional URL and returns a session_id. Call this first before any other session tools. Store the session_id for reuse throughout the SDET workflow.",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "Initial page URL for the session (optional)" },
        },
      },
      execute: async ({ url }) => {
        const res = await fetch(`${API_BASE}/api/session/init`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url || "" }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    sdet_session_context: {
      name: "sdet_session_context",
      description: "Get the full SDET session context including recorded actions, selected DOM elements with locators, generated test code, and conversation history. Call this at the start of an SDET task so the model has awareness of what has been done so far in the session.",
      parameters: {
        type: "object",
        properties: {
          session_id: { type: "string", description: "Session ID from sdet_session_init" },
        },
        required: ["session_id"],
      },
      execute: async ({ session_id }) => {
        const res = await fetch(`${API_BASE}/api/session/context`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },

    sdet_session_state: {
      name: "sdet_session_state",
      description: "Get a compact summary of the current SDET session state: action count, element count, whether test code exists, last action, and conversation turn count. Faster than sdet_session_context when you only need a status overview.",
      parameters: {
        type: "object",
        properties: {
          session_id: { type: "string", description: "Session ID from sdet_session_init" },
        },
        required: ["session_id"],
      },
      execute: async ({ session_id }) => {
        const res = await fetch(`${API_BASE}/api/session/context`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        const ctx = await res.json();
        return {
          session_id: ctx.session_id,
          url: ctx.url,
          action_count: ctx.recorded_actions?.length ?? 0,
          element_count: ctx.selected_elements?.length ?? 0,
          has_test_code: ctx.test_code !== null,
          test_language: ctx.test_code?.language ?? null,
          last_action: ctx.recorded_actions?.length > 0
            ? ctx.recorded_actions[ctx.recorded_actions.length - 1]
            : null,
          conversation_turn_count: ctx.conversation_history?.length ?? 0,
          updated_at: ctx.updated_at,
        };
      },
    },

    sdet_record_action: {
      name: "sdet_record_action",
      description: "Record a user action (click, type, select, navigate, hover) in the current SDET session. Use this whenever the user interacts with the page so the session context stays up to date for test generation. Include the CSS selector of the element interacted with.",
      parameters: {
        type: "object",
        properties: {
          session_id: { type: "string", description: "Session ID from sdet_session_init" },
          action_type: {
            type: "string",
            description: "Type of action: click | type | select | navigate | hover",
            enum: ["click", "type", "select", "navigate", "hover"],
          },
          selector: { type: "string", description: "CSS selector of the element interacted with" },
          value: { type: "string", description: "Value typed or selected (for type/select actions)" },
          url: { type: "string", description: "Current page URL (optional, defaults to session URL)" },
        },
        required: ["session_id", "action_type", "selector"],
      },
      execute: async ({ session_id, action_type, selector, value, url }) => {
        const res = await fetch(`${API_BASE}/api/session/record-action`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id, action_type, selector, value: value || "", url: url || "" }),
        });
        if (!res.ok) return { error: `HTTP ${res.status}` };
        return await res.json();
      },
    },
  },
};

export default plugin;
