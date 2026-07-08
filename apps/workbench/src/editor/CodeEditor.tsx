import { useMemo, useCallback } from "react";
import Editor from "@monaco-editor/react";

interface CodeEditorProps {
  value: string;
  language?: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  path?: string;
}

const EXT_LANG_MAP: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", json: "json", md: "markdown", css: "css",
  html: "html", yml: "yaml", yaml: "yaml", sh: "shell",
  bash: "shell", zsh: "shell", go: "go", rs: "rust",
  java: "java", kt: "kotlin", swift: "swift", rb: "ruby",
  php: "php", sql: "sql", xml: "xml", svg: "xml",
};

function inferLanguage(path?: string): string {
  if (!path) return "plaintext";
  const ext = path.split(".").pop()?.toLowerCase() || "";
  return EXT_LANG_MAP[ext] || "plaintext";
}

export default function CodeEditor({ value, language, onChange, readOnly, path }: CodeEditorProps) {
  const lang = useMemo(() => language || inferLanguage(path), [language, path]);

  const handleMount = useCallback((editor: any) => {
    editor.focus();
  }, []);

  const handleChange = useCallback((val: string | undefined) => {
    onChange?.(val || "");
  }, [onChange]);

  return (
    <div className="ce-container">
      <Editor
        height="100%"
        language={lang}
        value={value}
        onChange={handleChange}
        onMount={handleMount}
        theme="vs-dark"
        options={{
          readOnly: readOnly || false,
          minimap: { enabled: false },
          fontSize: 13,
          fontFamily: "'SF Mono', 'Fira Code', monospace",
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
          wordWrap: "off",
          renderWhitespace: "selection",
          padding: { top: 8 },
          smoothScrolling: true,
          cursorBlinking: "smooth",
          bracketPairColorization: { enabled: true },
        }}
      />
    </div>
  );
}
