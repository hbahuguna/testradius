import { useState, useCallback, useRef, useEffect } from "react";
import "./App.css";
import AgentPanel from "./sdet/AgentPanel";
import type { ContextElement, RecordedAction } from "./sdet/types";

const API_BASE = import.meta.env.VITE_WORKBENCH_API || "";
const SDET_API_BASE = import.meta.env.VITE_SDET_API || "http://localhost:8004";
const isElectron = navigator.userAgent.includes("Electron");

function proxyEncode(url: string): string {
  return btoa(url.replace(/\/+$/, ""))
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

const _INSPECTOR_SCRIPT = `
(function(){
  var h=null,s=null,st=document.createElement('style');
  st.textContent='.ts-h{outline:2px solid #4488ff!important;outline-offset:-1px!important;background:rgba(68,136,255,0.08)!important}.ts-sel{outline:3px solid #ff6644!important;outline-offset:-1px!important;background:rgba(255,102,68,0.12)!important}';
  document.head.appendChild(st);
  function rp(p){
    if(!p)return null;
    var parts=p.split(' > '),cur=document.body||document.documentElement;
    for(var i=0;i<parts.length;i++){
      var pt=parts[i],tag=pt.split(/[.#]/)[0];
      var m=pt.match(/#([^.#]+)/),id=m?m[1]:null;
      var cls=[];var re=/\\.([^.#]+)/g;var mc;
      while((mc=re.exec(pt))!==null)cls.push(mc[1]);
      var ch=cur.children,f=null;
      for(var j=0;j<ch.length;j++){
        var c=ch[j];if(c.tagName.toLowerCase()!==tag)continue;
        if(id&&c.id!==id)continue;
        if(cls.length>0){var ok=cls.every(function(x){return c.classList.contains(x)});if(!ok)continue;}
        f=c;break;
      }
      if(!f)return null;cur=f;
    }
    return cur;
  }
  function gp(el){
    if(el.id)return el.tagName.toLowerCase()+'#'+el.id;
    var parts=[];
    while(el&&el.nodeType===1){
      var sel=el.tagName.toLowerCase();
      if(el.id){parts.unshift(sel+'#'+el.id);break;}
      var p=el.parentElement;
      if(p){
        var sib=Array.from(p.children).filter(function(c){return c.tagName===el.tagName});
        if(sib.length>1)sel+=':nth-child('+(Array.from(p.children).indexOf(el)+1)+')';
      }
      parts.unshift(sel);el=p;
    }
    return parts.join(' > ');
  }
  document.addEventListener('mouseover',function(e){
    var el=e.target;
    if(el===document.body||el===document.documentElement)return;
    if(h)h.classList.remove('ts-h');h=el;el.classList.add('ts-h');e.stopPropagation();
  },true);
  document.addEventListener('mouseout',function(e){
    if(h){h.classList.remove('ts-h');h=null;}
  },true);
  var skipTags=['script','style','meta','link','base','head'];
  document.addEventListener('click',function(e){
    var el=e.target;
    if(el===document.body||el===document.documentElement)return;
    if(skipTags.indexOf(el.tagName.toLowerCase())!==-1)return;
    e.preventDefault();e.stopPropagation();
    if(s)s.classList.remove('ts-sel');
    if(h){h.classList.remove('ts-h');h=null;}
    s=el;el.classList.add('ts-sel');
    var inShadow=false,targetEl=el,root=el.getRootNode?el.getRootNode():document;
    if(root&&root instanceof ShadowRoot){inShadow=true;targetEl=root.host;}
    var path=gp(targetEl),tag=targetEl.tagName.toLowerCase(),text=(targetEl.textContent||'').trim().substring(0,100),id=targetEl.id||'',cls=Array.from(targetEl.classList).join('.');
    var msg=JSON.stringify({type:'ts-element-click',cssPath:path,tag:tag,text:text,id:id,classes:cls,inShadowDOM:inShadow});
    window.parent.postMessage(JSON.parse(msg),'*');
    console.log(msg);
  },true);
  window.addEventListener('message',function(e){
    var d=e.data;
    if(!d||!d.type)return;
    if(d.type==='ts-highlight'&&d.cssPath){
      if(h)h.classList.remove('ts-h');
      var el=rp(d.cssPath);if(el){h=el;el.classList.add('ts-h');}return;
    }
    if(d.type==='ts-clear-highlight'){if(h){h.classList.remove('ts-h');h=null;}return;}
    if(d.type==='ts-select'&&d.cssPath){
      if(s)s.classList.remove('ts-sel');if(h)h.classList.remove('ts-h');h=null;
      var el=rp(d.cssPath);if(el){s=el;el.classList.add('ts-sel');}return;
    }
  });
})();
`;

function inferActionType(tag: string, elType?: string): string {
  const t = tag.toLowerCase();
  if (elType === "checkbox" || (t === "input" && elType === "checkbox")) return "check";
  if (t === "select") return "select";
  if (t === "input" || t === "textarea") return "fill";
  if (t === "a" || t === "button") return "click";
  return "click";
}

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function App() {
  const [url, setUrl] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layout, setLayout] = useState<"horizontal" | "vertical">("horizontal");
  const [contextElements, setContextElements] = useState<ContextElement[]>([]);
  const [recordedActions, setRecordedActions] = useState<RecordedAction[]>([]);
  const [elementSelectionMode, setElementSelectionMode] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const webviewRef = useRef<any>(null);
  const webviewContainerRef = useRef<HTMLDivElement>(null);

  const handleElementClick = useCallback((data: { cssPath: string; tag: string; text: string; id: string; inShadowDOM?: boolean }) => {
    const actionType = inferActionType(data.tag);
    setContextElements(prev => {
      const existing = prev.find(el => el.cssPath === data.cssPath);
      if (existing) return prev;
      return [...prev, {
        id: genId(),
        cssPath: data.cssPath,
        tag: data.tag,
        text: data.text,
        elementId: data.id,
        actionType,
      }];
    });
    setRecordedActions(prev => {
      const existing = prev.find(a => a.css_path === data.cssPath);
      if (existing) return prev;
      const step = prev.length + 1;
      return [...prev, {
        css_path: data.cssPath,
        tag: data.tag,
        action_type: actionType,
        text: data.text,
        element_id: data.id,
        step_order: step,
      }];
    });
  }, []);

  const removeContextElement = useCallback((id: string) => {
    setContextElements(prev => prev.filter(el => el.id !== id));
  }, []);

  const clearContext = useCallback(() => {
    setContextElements([]);
    setRecordedActions([]);
  }, []);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "ts-element-click") {
        handleElementClick(e.data);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [handleElementClick]);

  useEffect(() => {
    if (!isElectron || !previewUrl || !webviewContainerRef.current) return;
    const container = webviewContainerRef.current;
    container.innerHTML = "";
    const webview = document.createElement("webview") as any;
    webview.src = previewUrl;
    webview.setAttribute("style", "width:100%;height:100%;border:none");
    webview.setAttribute("allowpopups", "");
    container.appendChild(webview);
    webviewRef.current = webview;
    const onDomReady = () => {
      webview.executeJavaScript(_INSPECTOR_SCRIPT).catch(() => {});
    };
    const onConsoleMessage = (e: { message: string }) => {
      try {
        const msg = JSON.parse(e.message);
        if (msg.type === "ts-element-click") handleElementClick(msg);
      } catch {}
    };
    webview.addEventListener("dom-ready", onDomReady);
    webview.addEventListener("console-message", onConsoleMessage);
    return () => {
      webview.removeEventListener("dom-ready", onDomReady);
      webview.removeEventListener("console-message", onConsoleMessage);
    };
  }, [previewUrl, handleElementClick]);

  const handleGo = useCallback(async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setContextElements([]);
    setRecordedActions([]);
    setElementSelectionMode(false);
    setPreviewUrl(url.trim());
    setLoading(false);
  }, [url]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleGo();
  };

  const previewSrc = previewUrl ? `${API_BASE}/v/${proxyEncode(previewUrl)}/` : null;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <h1>TestSquad Workbench</h1>
          <div className="layout-toggle">
            <button
              className={`layout-btn ${layout === "horizontal" ? "active" : ""}`}
              onClick={() => setLayout("horizontal")}
              title="Side by side"
            >
              &#x2194;
            </button>
            <button
              className={`layout-btn ${layout === "vertical" ? "active" : ""}`}
              onClick={() => setLayout("vertical")}
              title="Stack vertically"
            >
              &#x2195;
            </button>
          </div>
        </div>
        <div className="toolbar">
          <input
            className="url-bar"
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter URL (e.g. https://example.com)"
          />
          <button className="go-btn" onClick={handleGo} disabled={loading}>
            {loading ? "..." : "Go"}
          </button>
        </div>
        {error && <div className="error-bar">{error}</div>}
      </header>

      <main className={`app-main ${layout}`}>
        <section className="panel preview-panel">
          <div className="panel-header">
            Visual Preview
            <span className="count">{contextElements.length} element{contextElements.length !== 1 ? "s" : ""} selected</span>
          </div>
          <div className="preview-content" style={{ position: "relative" }}>
            {previewUrl && previewSrc ? (
              <>
                {isElectron ? (
                  <div ref={webviewContainerRef} className="preview-iframe" />
                ) : (
                  <iframe
                    ref={iframeRef}
                    className="preview-iframe"
                    src={previewSrc}
                    title="Page Preview"
                  />
                )}
                {elementSelectionMode && (
                  <div className="pv-overlay">
                    <div className="pv-overlay-content">
                      <div className="pv-overlay-icon">&#9678;</div>
                      <div className="pv-overlay-title">Element Selection Mode</div>
                      <div className="pv-overlay-text">
                        Click on the page elements you want to include in your test.
                        Selected elements will appear as chips below the chat.
                      </div>
                      <div className="pv-overlay-count">
                        {contextElements.length} element{contextElements.length !== 1 ? "s" : ""} selected
                      </div>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="placeholder">Enter a URL and click Go to preview a page.</div>
            )}
          </div>
        </section>

        <section className="panel agent-panel">
          <div className="panel-header">
            <span>SDET Agent</span>
            <span className="count">{contextElements.length} element{contextElements.length !== 1 ? "s" : ""} selected</span>
          </div>
          <AgentPanel
            apiBase={SDET_API_BASE}
            url={previewUrl || ""}
            contextElements={contextElements}
            recordedActions={recordedActions}
            onRemoveElement={removeContextElement}
            onClearElements={clearContext}
            onElementSelectionChange={setElementSelectionMode}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
