export interface ExecuteStep {
  step: number;
  action: string;
  target: string;
  kind?: string;
  value?: string;
  ok: boolean;
  thought?: string;
  url?: string;
  interactive_elements?: unknown[];
  duration_ms?: number;
  timestamp?: string;
}

export interface ExecuteAssertion {
  type: string;
  description?: string;
  passed?: boolean;
  detail?: string;
}

export interface ExecuteResult {
  success: boolean;
  goal_reached?: boolean;
  error?: string;
  generated_code?: string | null;
  trace?: {
    goal: string;
    url: string;
    backend: string;
    goal_reached?: boolean;
    final_url?: string;
    total_duration_ms?: number;
    token_estimate?: number;
    steps: ExecuteStep[];
    assertions: ExecuteAssertion[];
  };
}

export interface HealResult {
  success: boolean;
  original_code?: string;
  healed_code?: string;
  changed_locators?: string[];
  verification?: { passed?: boolean; error?: string; detail?: string };
  error?: string;
}

export interface GenerateRunResult {
  generated_code?: string | null;
  generate_error?: string | null;
  attempts?: Array<{
    attempt: number;
    assertions: Array<Record<string, unknown>>;
    execute: ExecuteResult;
    heal: HealResult | null;
  }>;
  execute?: ExecuteResult | null;
  heal?: HealResult | null;
  success?: boolean;
}

export interface ObservationPage {
  url: string;
  action_taken?: string | null;
  interactive_elements?: Array<{ role?: string; name?: string; tag?: string }>;
  page_text?: string;
}

export interface GenerateAgenticResult {
  generated_code?: string | null;
  generate_error?: string | null;
  observations?: ObservationPage[];
  exploration_log?: string[];
  attempts?: Array<{
    attempt: number;
    execute: ExecuteResult;
    heal: HealResult | null;
  }>;
  execute?: ExecuteResult | null;
  heal?: HealResult | null;
  success?: boolean;
}

export async function generateAgentic(
  apiBase: string,
  p: {
    goal: string;
    url: string;
    repo_dir?: string | null;
    test_path?: string;
    starting_url?: string;
    backend?: string;
    headless?: boolean;
    max_explore_turns?: number;
    max_attempts?: number;
  }
): Promise<GenerateAgenticResult> {
  const resp = await fetch(`${apiBase}/api/workbench/agentic/generate-agentic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      goal: p.goal,
      url: p.url,
      repo_dir: p.repo_dir ?? null,
      test_path: p.test_path,
      starting_url: p.starting_url ?? "",
      backend: p.backend ?? "mcp",
      headless: p.headless ?? true,
      max_explore_turns: p.max_explore_turns ?? 8,
      max_attempts: p.max_attempts ?? 5,
    }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
  }
  return (await resp.json()) as GenerateAgenticResult;
}

export async function generateRun(
  apiBase: string,
  p: {
    scenario: string;
    url: string;
    goal: string;
    assertions?: Record<string, unknown>[];
    repo_dir?: string | null;
    test_path?: string;
    generated_code?: string | null;
    backend?: string;
    headless?: boolean;
    max_turns?: number;
    max_attempts?: number;
  }
): Promise<GenerateRunResult> {
  const resp = await fetch(`${apiBase}/api/workbench/agentic/generate-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario: p.scenario,
      url: p.url,
      goal: p.goal,
      assertions: p.assertions || [],
      repo_dir: p.repo_dir ?? null,
      test_path: p.test_path,
      generated_code: p.generated_code ?? null,
      backend: p.backend ?? "mcp",
      headless: p.headless ?? true,
      max_turns: p.max_turns ?? 30,
      max_attempts: p.max_attempts ?? 5,
    }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
  }
  return (await resp.json()) as GenerateRunResult;
}
