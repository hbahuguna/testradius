export interface ContextElement {
  id: string;
  cssPath: string;
  tag: string;
  text: string;
  elementId: string;
  actionType?: string;
  value?: string;
}

export interface LocatorOption {
  type: string;
  value: string;
  strategy: string;
  label: string;
  brittleness: number;
}

export interface RecordedAction {
  css_path: string;
  locator_type: string;
  tag: string;
  action_type: string;
  value?: string;
  text?: string;
  step_order?: number;
  element_id?: string;
  label?: string;
  locator?: string;
}

export interface PendingElement {
  tag: string;
  text: string;
  id: string;
  classes: string;
  cssPath: string;
  attributes: Record<string, string>;
  locators: LocatorOption[];
  selectedLocator: LocatorOption | null;
  value?: string; // Add value for inputs/selects
}

export interface Step {
  nodeId: string;
  nodeName: string;
  agentMessage: string;
  userMessage: string | null;
  elements: ContextElement[];
  code: string | null;
  isExpanded: boolean;
  isRemovable: boolean;
}

export interface NodeInfo {
  id: string;
  name: string;
  type: "hub" | "agent" | "user";
}

export const ALL_NODES: NodeInfo[] = [
  { id: "N0", name: "Open", type: "agent" },
  { id: "N1", name: "Request", type: "user" },
  { id: "N2", name: "Parse", type: "agent" },
  { id: "N3", name: "Clarify", type: "hub" },
  { id: "N4", name: "Details", type: "user" },
  { id: "N5", name: "Intent", type: "agent" },
  { id: "N6", name: "Test Type", type: "hub" },
  { id: "N7", name: "Journey", type: "agent" },
  { id: "N8", name: "Feature", type: "hub" },
  { id: "N9", name: "Elements", type: "agent" },
  { id: "N10", name: "Locators", type: "agent" },
  { id: "N11", name: "Actions", type: "agent" },
  { id: "N12", name: "Assertions", type: "agent" },
  { id: "N13", name: "Hardening", type: "agent" },
  { id: "N14", name: "Generate", type: "agent" },
  { id: "N15", name: "Review", type: "hub" },
];

export const NODE_NAME_MAP: Record<string, string> = Object.fromEntries(
  ALL_NODES.map((n) => [n.id, n.name])
);

export const NODE_TYPE_MAP: Record<string, string> = Object.fromEntries(
  ALL_NODES.map((n) => [n.id, n.type])
);

export const PHASE_MAP: Record<string, string> = {
  N0: "Understanding your test scenario",
  N1: "Understanding your test scenario",
  N2: "Analyzing your requirements",
  N3: "Clarifying your requirements",
  N4: "Learning more about your scenario",
  N5: "Determining the test approach",
  N6: "Choosing the test type",
  N7: "Mapping the user journey",
  N8: "Identifying the feature under test",
  N9: "Identifying page elements",
  N10: "Building element locators",
  N11: "Defining test actions",
  N12: "Setting up assertions",
  N13: "Hardening the test",
  N14: "Generating the test",
  N15: "Reviewing the test",
};

export function getPhaseLabel(nodeId: string): string {
  return PHASE_MAP[nodeId] || "Working on your test";
}

const NODE_ID_RE = /^\[(N\d+)\]/;

export function extractNodeId(content: string): string | null {
  const m = NODE_ID_RE.exec(content);
  return m ? m[1] : null;
}

export function getNodeName(nodeId: string): string {
  return NODE_NAME_MAP[nodeId] || nodeId;
}

export function messageToStep(
  msg: { role: string; content: string },
  index: number,
  totalCount: number
): Step {
  const nodeId = extractNodeId(msg.content) || `N${Math.min(index * 2, 15)}`;
  return {
    nodeId,
    nodeName: getNodeName(nodeId),
    agentMessage: msg.content,
    userMessage: null,
    elements: [],
    code: null,
    isExpanded: index === totalCount - 1,
    isRemovable: index > 0,
  };
}

export function buildSteps(messages: { role: string; content: string }[]): Step[] {
  const assistantMsgs = messages.filter((m) => m.role === "assistant");
  return assistantMsgs.map((msg, i) => {
    const step = messageToStep(msg, i, assistantMsgs.length);
    const msgIdx = messages.indexOf(msg);
    const nextMsgs = messages.slice(msgIdx + 1);
    const userMsg = nextMsgs.find((m) => m.role === "user");
    if (userMsg) step.userMessage = userMsg.content;
    return step;
  });
}

export interface MessageGroup {
  nodeId: string;
  phaseLabel: string;
  agentMessage: string;
  userMessage: string | null;
  code: string | null;
  isLast: boolean;
}

export function buildMessageGroups(messages: { role: string; content: string }[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  const assistantMsgs = messages.filter((m) => m.role === "assistant");
  for (let i = 0; i < assistantMsgs.length; i++) {
    const msg = assistantMsgs[i];
    const nodeId = extractNodeId(msg.content) || `N${Math.min(i * 2, 15)}`;
    const msgIdx = messages.indexOf(msg);
    const nextMsgs = messages.slice(msgIdx + 1);
    const userMsg = nextMsgs.find((m) => m.role === "user");
    const code = extractCode(msg.content);
    groups.push({
      nodeId,
      phaseLabel: getPhaseLabel(nodeId),
      agentMessage: stripNodeTag(msg.content),
      userMessage: userMsg ? userMsg.content : null,
      code,
      isLast: i === assistantMsgs.length - 1,
    });
  }
  return groups;
}

function extractCode(content: string): string | null {
  const m = content.match(/```[\w]*\n([\s\S]*?)```/);
  return m ? m[1].trim() : null;
}

function stripNodeTag(content: string): string {
  return content.replace(/^\[N\d+\]\s*/, "");
}

export interface OpenCodeToolEvent {
  type: "opencode_event";
  event: string;
  tool?: string;
  status?: string;
  content?: string;
  path?: string;
  command?: string;
  output?: string;
  reason?: string;
}

export interface OpenCodeCompleteEvent {
  type: "opencode_complete";
  test_code?: string;
}

export interface OpenCodeErrorEvent {
  type: "opencode_error";
  content: string;
}

export type OpenCodeEvent = OpenCodeToolEvent | OpenCodeCompleteEvent | OpenCodeErrorEvent;
