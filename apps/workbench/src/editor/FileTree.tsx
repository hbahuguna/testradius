import { useState, useEffect, useCallback } from "react";

interface DirEntry {
  name: string;
  type: "file" | "dir";
  path: string;
}

interface FileTreeProps {
  apiBase: string;
  repoDir: string;
  onFileSelect: (path: string) => void;
  selectedFile: string | null;
}

function extensionIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const iconMap: Record<string, string> = {
    ts: "\u03bb", py: "\u2699", js: "\u2699",
    json: "{ }", yml: "\u2699", yaml: "\u2699",
    md: "M", css: "#", html: "</>",
    spec: "\u2713", test: "\u2713",
  };
  return iconMap[ext] || "\u2022";
}

export default function FileTree({ apiBase, repoDir, onFileSelect, selectedFile }: FileTreeProps) {
  const [tree, setTree] = useState<DirEntry[]>([]);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(["."]));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirContents, setDirContents] = useState<Record<string, DirEntry[]>>({});

  const fetchDir = useCallback(async (subPath: string) => {
    if (!repoDir) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/repo/tree`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: repoDir, sub_path: subPath }),
      });
      if (!res.ok) throw new Error(`Failed to list: ${res.status}`);
      const data = await res.json();
      setDirContents(prev => ({ ...prev, [subPath]: data.entries }));
      return data.entries as DirEntry[];
    } catch (e: any) {
      setError(e.message);
      return [];
    } finally {
      setLoading(false);
    }
  }, [apiBase, repoDir]);

  useEffect(() => {
    if (repoDir) fetchDir(".");
  }, [repoDir, fetchDir]);

  const toggleDir = useCallback(async (path: string) => {
    const next = new Set(expandedDirs);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
      if (!dirContents[path]) await fetchDir(path);
    }
    setExpandedDirs(next);
  }, [expandedDirs, dirContents, fetchDir]);

  function renderTree(entries: DirEntry[], parentPath: string): React.ReactNode {
    const sorted = [...entries].sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    return sorted.map((entry) => {
      const fullPath = parentPath === "." ? entry.path : `${parentPath}/${entry.path}`;
      if (entry.type === "dir") {
        const isExpanded = expandedDirs.has(fullPath);
        return (
          <div key={fullPath}>
            <div
              className="ft-node ft-dir"
              onClick={() => toggleDir(fullPath)}
            >
              <span className="ft-chevron">{isExpanded ? "\u25BC" : "\u25B6"}</span>
              <span className="ft-icon ft-dir-icon">\uD83D\uDCC1</span>
              <span className="ft-name">{entry.name}</span>
            </div>
            {isExpanded && dirContents[fullPath] && (
              <div className="ft-children">
                {renderTree(dirContents[fullPath], fullPath)}
              </div>
            )}
          </div>
        );
      }
      const isSelected = selectedFile === fullPath;
      return (
        <div
          key={fullPath}
          className={`ft-node ft-file ${isSelected ? "ft-selected" : ""}`}
          onClick={() => onFileSelect(fullPath)}
        >
          <span className="ft-indent" />
          <span className="ft-icon ft-file-icon">{extensionIcon(entry.name)}</span>
          <span className="ft-name">{entry.name}</span>
        </div>
      );
    });
  }

  return (
    <div className="ft-panel">
      <div className="ft-header">
        <span className="ft-title">Files</span>
        {loading && <span className="ft-spinner" />}
      </div>
      <div className="ft-tree">
        {!repoDir ? (
          <div className="ft-empty">Set a repo path above to browse files</div>
        ) : error ? (
          <div className="ft-error">{error}</div>
        ) : dirContents["."] ? (
          renderTree(dirContents["."], ".")
        ) : loading ? (
          <div className="ft-loading">Loading...</div>
        ) : (
          <div className="ft-empty">No files found</div>
        )}
      </div>
    </div>
  );
}
