import React, { useState, useEffect, useRef } from 'react';
import { X, FlaskConical, StopCircle, Play } from 'lucide-react';
import { useGithub } from '../contexts/GithubProvider';
import API_BASE from '../config';

let _instrumentationStream = {
  logs: [],
  status: 'idle',
  running: false,
  abortController: null,
  projectId: null,
};

const getRepoName = (url) => {
  if (!url) return '';
  const match = url.match(/github\.com\/([^/]+\/[^/]+?)(?:\.git)?$/);
  return match ? match[1] : url;
};

const InstrumentationModal = ({ projectId, repoUrl, onClose }) => {
  const { fetchWithGithub } = useGithub();
  const mountedRef = useRef(true);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('idle');
  const [cancelling, setCancelling] = useState(false);
  const [language, setLanguage] = useState('python');
  const [testbedName, setTestbedName] = useState('blacktrigram');
  const [started, setStarted] = useState(false);
  const [localPath, setLocalPath] = useState('');
  const repoDisplayName = getRepoName(repoUrl);

  useEffect(() => {
    if (language === 'playwright') {
      if (testbedName === 'blacktrigram' || testbedName === 'zod' || testbedName === 'hono') {
        setTestbedName('testradius');
      }
    } else if (language === 'typescript') {
      if (testbedName === 'testradius') {
        setTestbedName('blacktrigram');
      }
    }
  }, [language]);

  useEffect(() => {
    mountedRef.current = true;

    const updateFromStream = (newLog, newStatus) => {
      if (mountedRef.current) {
        if (newLog) setLogs(prev => [...prev, newLog]);
        if (newStatus) setStatus(newStatus);
      }
    };

    const startStream = async () => {
      _instrumentationStream.status = 'starting';
      _instrumentationStream.running = true;
      _instrumentationStream.projectId = projectId;

      updateFromStream(null, 'starting');

      const abortController = new AbortController();
      _instrumentationStream.abortController = abortController;

      try {
        const bodyPayload = { language };
        if (language === 'typescript' || language === 'playwright') {
          if (testbedName === '__custom__') {
            // Custom repo: don't send testbed_name, backend auto-detects config
          } else {
            bodyPayload.testbed_name = testbedName;
          }
        }
        if (language === 'playwright' && localPath) bodyPayload.local_path = localPath;
        if (repoUrl) bodyPayload.repo_url = repoUrl;
        const body = JSON.stringify(bodyPayload);

        const res = await fetchWithGithub(
          `${API_BASE}/projects/${projectId}/instrumentation/run`,
          {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body,
            signal: abortController.signal
          }
        );

        if (!res.ok) throw new Error(`Instrumentation request failed: ${res.status}`);

        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('text/event-stream')) {
          const reader = res.body.getReader();
          const decoder = new TextDecoder();

          while (mountedRef.current) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const parts = text.split('\n\n');
            for (let line of parts) {
              if (line.startsWith('data: ')) {
                try {
                  const payloadDoc = JSON.parse(line.replace('data: ', ''));
                  const logEntry = {
                    type: payloadDoc.event,
                    content: payloadDoc.data,
                    timestamp: new Date().toLocaleTimeString()
                  };
                  _instrumentationStream.logs.push(logEntry);

                  if (payloadDoc.event === 'status') {
                    const s = payloadDoc.data.status === 'COMPLETED' ? 'success' : 'failed';
                    _instrumentationStream.status = s;
                    _instrumentationStream.running = false;
                    updateFromStream(logEntry, s);
                    if (payloadDoc.data.status === 'COMPLETED') return;
                  } else if (payloadDoc.event === 'error') {
                    _instrumentationStream.status = 'failed';
                    _instrumentationStream.running = false;
                    updateFromStream(logEntry, 'failed');
                  } else {
                    updateFromStream(logEntry, null);
                  }
                } catch(e) {}
              }
            }
          }
        } else {
          const data = await res.json();
          const logEntry = {
            type: 'status',
            content: data.message || 'Instrumentation completed',
            timestamp: new Date().toLocaleTimeString()
          };
          _instrumentationStream.logs.push(logEntry);
          _instrumentationStream.status = 'success';
          _instrumentationStream.running = false;
          updateFromStream(logEntry, 'success');
        }
      } catch (e) {
        if (e.name !== 'AbortError') {
          const logEntry = {
            type: 'error',
            content: e.message,
            timestamp: new Date().toLocaleTimeString()
          };
          _instrumentationStream.logs.push(logEntry);
          _instrumentationStream.status = 'failed';
          _instrumentationStream.running = false;
          updateFromStream(logEntry, 'failed');
        }
      }
    };

    if (_instrumentationStream.running && _instrumentationStream.projectId === projectId) {
      setLogs([..._instrumentationStream.logs]);
      setStatus(_instrumentationStream.status);
      setStarted(true);
    } else if (!_instrumentationStream.running && _instrumentationStream.status === 'success') {
      setLogs([..._instrumentationStream.logs]);
      setStatus(_instrumentationStream.status);
      setStarted(true);
    } else if (started && (_instrumentationStream.status === 'idle' || !_instrumentationStream.running)) {
      _instrumentationStream.logs = [];
      _instrumentationStream.status = 'idle';
      _instrumentationStream.running = false;
      startStream();
    }

    return () => {
      mountedRef.current = false;
    };
  }, [projectId, repoUrl, language, testbedName, started, localPath]);

  const handleCancel = async () => {
    setCancelling(true);
    try {
      await fetchWithGithub(
        `${API_BASE}/projects/${projectId}/instrumentation/cancel`,
        { method: 'POST' }
      );
    } catch (e) {
      console.error('Cancel request failed:', e);
    }
  };

  const isRunning = started && (status === 'starting' || status === 'idle');

  return (
    <div className="modal-overlay glass animate-in" style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      backdropFilter: 'blur(8px)', background: 'rgba(0,0,0,0.6)'
    }}>
      <div className="glass" style={{
        width: '800px', height: '600px', background: 'rgba(13, 17, 23, 0.95)',
        borderRadius: '1.5rem', display: 'flex', flexDirection: 'column',
        border: '1px solid rgba(255,255,255,0.1)', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)'
      }}>
        <div style={{ padding: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FlaskConical size={20} color="var(--accent-blue)" className={isRunning ? 'pulse' : ''} />
            <h3 style={{ margin: 0, color: 'var(--accent-blue)' }}>Coverage Instrumentation</h3>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
            <X size={24} />
          </button>
        </div>

        <div style={{ padding: '1rem 1.5rem', background: 'rgba(0,0,0,0.2)', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <p style={{ margin: 0, color: 'rgba(255,255,255,0.7)', fontSize: '0.875rem' }}>
            {!started
              ? `Configure instrumentation for ${language === 'typescript' || language === 'playwright' ? `${testbedName === '__custom__' ? repoDisplayName : testbedName} (${language === 'typescript' ? 'TypeScript' : 'Playwright'})` : 'Python'}`
              : (repoUrl ? `Mapping coverage for ${repoUrl}` : 'Running coverage instrumentation...')}
          </p>
          {started && isRunning && !cancelling && (
            <button onClick={handleCancel} style={{
              background: 'rgba(255,80,80,0.15)', border: '1px solid rgba(255,80,80,0.3)',
              color: '#ff7b72', cursor: 'pointer', borderRadius: '0.5rem',
              padding: '0.35rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem',
              fontSize: '0.8rem', fontWeight: 600
            }}>
              <StopCircle size={14} /> Cancel
            </button>
          )}
          {cancelling && (
            <span style={{ color: '#ff7b72', fontSize: '0.8rem' }}>Cancelling...</span>
          )}
        </div>

        <div style={{ flex: 1, padding: '1rem', background: '#0a0c10', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {!started ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: '1.5rem' }}>
              <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.95rem', textAlign: 'center' }}>
                Select language and testbed, then click Start
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', width: '300px' }}>
                <label style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.8rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Language</label>
                <select value={language} onChange={e => setLanguage(e.target.value)}
                  style={{
                    background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)',
                    color: '#c9d1d9', borderRadius: '0.5rem', padding: '0.6rem 0.75rem',
                    fontSize: '0.875rem', cursor: 'pointer', outline: 'none'
                  }}>
                  <option value="python">Python</option>
                  <option value="typescript">TypeScript</option>
                  <option value="playwright">Playwright</option>
                </select>
              </div>

              {(language === 'typescript' || language === 'playwright') && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', width: '300px' }}>
                  <label style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.8rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Testbed Repository</label>
                  <select value={testbedName} onChange={e => setTestbedName(e.target.value)}
                    style={{
                      background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)',
                      color: '#c9d1d9', borderRadius: '0.5rem', padding: '0.6rem 0.75rem',
                      fontSize: '0.875rem', cursor: 'pointer', outline: 'none'
                    }}>
                    {language === 'typescript' ? (
                      <>
                        <option value="blacktrigram">Blacktrigram</option>
                        <option value="zod">Zod</option>
                        <option value="hono">Hono</option>
                      </>
                    ) : (
                      <>
                        <option value="testradius">TestRadius</option>
                      </>
                    )}
                    {repoDisplayName && <option value="__custom__">{repoDisplayName} (Selected Repo)</option>}
                  </select>
                </div>
              )}

              {language === 'playwright' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', width: '300px' }}>
                  <label style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.8rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Local Project Path</label>
                  <input type="text" value={localPath} onChange={e => setLocalPath(e.target.value)}
                    placeholder="/path/to/project"
                    style={{
                      background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)',
                      color: '#c9d1d9', borderRadius: '0.5rem', padding: '0.6rem 0.75rem',
                      fontSize: '0.875rem', outline: 'none'
                    }} />
                </div>
              )}

              <button onClick={() => setStarted(true)}
                style={{
                  background: 'linear-gradient(135deg, #58a6ff, #0d6efd)',
                  border: 'none', color: 'white', borderRadius: '0.75rem',
                  padding: '0.75rem 2rem', cursor: 'pointer', fontWeight: 600,
                  fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '0.5rem',
                  boxShadow: '0 4px 12px rgba(13,110,253,0.3)'
                }}>
                <Play size={18} /> Start Instrumentation
              </button>
            </div>
          ) : (
            <>
              {logs.length === 0 && isRunning && (
                <div style={{ color: 'rgba(255,255,255,0.4)', fontStyle: 'italic', padding: '1rem' }}>
                  <span className="pulse">●</span> Initiating instrumentation...
                </div>
              )}
              {logs.map((log, idx) => (
                <div key={idx} style={{
                  color: log.type === 'error' ? '#ff7b72' : log.type === 'progress' || log.type === 'reasoning' ? '#a5d6ff' : log.type === 'mapping' ? '#7ee787' : '#c9d1d9',
                  animation: 'fadeIn 0.3s ease-out'
                }}>
                  <span style={{ opacity: 0.5 }}>{log.timestamp}</span> &nbsp;
                  {log.type === 'error' ? '❌ ' : log.type === 'status' ? '✅ ' : log.type === 'mapping' ? '🔗 ' : log.type === 'progress' ? '▶ ' : '⚡ '}
                  {typeof log.content === 'string' ? log.content : JSON.stringify(log.content)}
                </div>
              ))}
              {isRunning && logs.length > 0 && (
                <div style={{ color: 'rgba(255,255,255,0.4)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                  <span className="pulse">●</span> Processing...
                </div>
              )}
              {status === 'success' && (
                <div style={{ color: '#4caf50', marginTop: '1rem', fontWeight: 600 }}>✅ Instrumentation completed successfully!</div>
              )}
              {status === 'failed' && (
                <div style={{ color: '#ff7b72', marginTop: '1rem', fontWeight: 600 }}>❌ Instrumentation failed.</div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default InstrumentationModal;
