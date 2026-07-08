import { useState, useCallback, useEffect, useRef } from "react";
import FileTree from "./FileTree";
import CodeEditor from "./CodeEditor";

interface EditorPanelProps {
  apiBase: string;
  repoDir: string;
}

interface OpenFile {
  path: string;
  content: string;
  originalContent: string;
  language?: string;
  dirty: boolean;
}

export default function EditorPanel({ apiBase, repoDir }: EditorPanelProps) {
  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeFile = openFiles.find((f) => f.path === activePath) || null;

  const openFile = useCallback(async (filePath: string) => {
    const existing = openFiles.find((f) => f.path === filePath);
    if (existing) {
      setActivePath(filePath);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/repo/read`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: repoDir, file_path: filePath }),
      });
      if (!res.ok) throw new Error(`Failed to read: ${res.status}`);
      const data = await res.json();
      const newFile: OpenFile = {
        path: filePath,
        content: data.content,
        originalContent: data.content,
        dirty: false,
      };
      setOpenFiles((prev) => [...prev, newFile]);
      setActivePath(filePath);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase, repoDir, openFiles]);

  const handleEditorChange = useCallback((value: string) => {
    if (!activePath) return;
    setOpenFiles((prev) =>
      prev.map((f) =>
        f.path === activePath
          ? { ...f, content: value, dirty: value !== f.originalContent }
          : f
      )
    );
  }, [activePath]);

  const closeFile = useCallback((filePath: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setOpenFiles((prev) => {
      const idx = prev.findIndex((f) => f.path === filePath);
      const next = prev.filter((f) => f.path !== filePath);
      if (activePath === filePath && next.length > 0) {
        const newIdx = Math.min(idx, next.length - 1);
        setActivePath(next[newIdx].path);
      } else if (activePath === filePath) {
        setActivePath(null);
      }
      return next;
    });
  }, [activePath]);

  const saveFile = useCallback(async () => {
    if (!activeFile || !activeFile.dirty) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/repo/write`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_path: repoDir,
          file_path: activeFile.path,
          content: activeFile.content,
        }),
      });
      if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
      setOpenFiles((prev) =>
        prev.map((f) =>
          f.path === activeFile.path
            ? { ...f, dirty: false, originalContent: f.content }
            : f
        )
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }, [apiBase, repoDir, activeFile]);

  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    if (!activeFile?.dirty) return;
    saveTimerRef.current = setTimeout(() => {
      saveFile();
    }, 3000);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [activeFile?.content, activeFile?.dirty, saveFile]);

  return (
    <section className="panel editor-panel">
      <div className="ep-layout">
        <FileTree
          apiBase={apiBase}
          repoDir={repoDir}
          onFileSelect={openFile}
          selectedFile={activePath}
        />
        <div className="ep-main">
          <div className="ep-tabs">
            {openFiles.length === 0 && (
              <span className="ep-tabs-empty">Select a file from the tree to edit</span>
            )}
            {openFiles.map((f) => {
              const name = f.path.split("/").pop() || f.path;
              return (
                <div
                  key={f.path}
                  className={`ep-tab ${f.path === activePath ? "ep-tab-active" : ""}`}
                  onClick={() => setActivePath(f.path)}
                >
                  <span className="ep-tab-name">{name}</span>
                  {f.dirty && <span className="ep-tab-dirty">\u25CF</span>}
                  <button className="ep-tab-close" onClick={(e) => closeFile(f.path, e)}>&times;</button>
                </div>
              );
            })}
            <div className="ep-tabs-actions">
              {activeFile?.dirty && (
                <button className="ep-save-btn" onClick={saveFile} disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </button>
              )}
            </div>
          </div>
          <div className="ep-editor-wrap">
            {loading && <div className="ep-loading">Loading...</div>}
            {error && <div className="ep-error">{error}</div>}
            {activeFile ? (
              <CodeEditor
                value={activeFile.content}
                onChange={handleEditorChange}
                path={activeFile.path}
              />
            ) : !loading && (
              <div className="placeholder ep-placeholder">
                Select a file from the tree to start editing
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
