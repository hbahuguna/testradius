/// <reference types="vite/client" />

interface ElectronWebview extends HTMLElement {
  src: string;
  executeJavaScript(code: string): Promise<unknown>;
  addEventListener(event: string, handler: (...args: any[]) => void): void;
  loadURL(url: string): Promise<void>;
}

interface ConsoleMessageEvent {
  message: string;
  level: number;
  sourceId: string;
  line: number;
}
