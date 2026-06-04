import React, { useState, useEffect } from 'react';
import { X, CheckCircle, XCircle, RefreshCw, Cpu, Search, Download, Zap } from 'lucide-react';
import { useGithub } from '../contexts/GithubProvider';
import API_BASE from '../config';

const TestMappingMatrix = ({ projectId, onClose, autoRepoName, autoRepoUrl, llmModel, setLlmModel, fetchedModels, isLoadingModels, onOpenInstrumentation }) => {
    const { fetchWithGithub, serverFeatures } = useGithub();
    const [mappings, setMappings] = useState([]);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [syncLogs, setSyncLogs] = useState([]);
    const [syncConfiguring, setSyncConfiguring] = useState(false);
    const [offset, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [useVector, setUseVector] = useState(false);
    const [activeTab, setActiveTab] = useState('all');
    const [useInstrumentation, setUseInstrumentation] = useState(false);
    const [testRepoUrl, setTestRepoUrl] = useState('');
    const [runFresh, setRunFresh] = useState(false);
    const [sourceFilter, setSourceFilter] = useState(null);
    const LIMIT = 50;

    const fetchMappings = async (newOffset = 0, search = searchTerm, source = sourceFilter) => {
        try {
            if (newOffset === 0) setLoading(true);
            const queryParam = search ? `&query=${encodeURIComponent(search)}` : '';
            const sourceParam = source ? `&source=${source}` : '';
            const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/test-mapping?limit=${LIMIT}&offset=${newOffset}${queryParam}${sourceParam}`);
            if (res.ok) {
                const data = await res.json();
                if (newOffset === 0) {
                    setMappings(data);
                } else {
                    setMappings(prev => [...prev, ...data]);
                }
                setHasMore(data.length === LIMIT);
                setOffset(newOffset);
            }
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        const delayDebounce = setTimeout(() => {
            fetchMappings(0, searchTerm, sourceFilter);
        }, 500);
        return () => clearTimeout(delayDebounce);
    }, [searchTerm, sourceFilter]);

    useEffect(() => {
        fetchMappings(0, '', null);
        setActiveTab('all');
    }, [projectId]);

    const handleTabChange = (tab) => {
        setActiveTab(tab);
        if (tab === 'coverage') {
            setSourceFilter('instrumentation');
        } else {
            setSourceFilter(null);
        }
    };

    const startSyncProcess = () => {
        setSyncConfiguring(false);
        handleSync();
    };

    const handleSync = async () => {
        const isStructuralOnly = !llmModel && !useVector && !useInstrumentation;
        const modeLabel = useInstrumentation ? 'Instrumentation' : isStructuralOnly ? 'Structural' : useVector ? 'Vector' : llmModel;
        
        setSyncing(true);
        setSyncLogs([{ type: 'log', content: `🚀 Starting ${modeLabel} mapping engine...` }]);
        
        const headers = { 
            'x-llm-model': llmModel || '',
            'x-use-vector': useVector ? 'true' : 'false',
            'x-use-instrumentation': useInstrumentation ? 'true' : 'false'
        };
        
        if (useInstrumentation) {
            if (testRepoUrl) headers['x-test-repo-url'] = testRepoUrl;
            if (runFresh) headers['x-run-fresh'] = 'true';
        }
        
        try {
            const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/map-tests`, {
                method: 'POST',
                headers
            });
            
            if (!res.ok) throw new Error("Mapping request failed");
            
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep partial line in buffer
                
                for (let line of lines) {
                    if (line.trim().startsWith('data: ')) {
                        try {
                            const rawJson = line.trim().replace('data: ', '');
                            const payload = JSON.parse(rawJson);
                            
                            if (payload.event === 'status' && payload.data.status === 'COMPLETED') {
                                setSyncing(false);
                                setTimeout(() => fetchMappings(0), 1000);
                            } else {
                                // Only keep last 50 logs to prevent UI lag
                                setSyncLogs(prev => [...prev, payload].slice(-50));
                            }
                        } catch(e) {
                            console.error("Failed to parse SSE line", line, e);
                        }
                    }
                }
            }
        } catch (e) {
            setSyncLogs(prev => [...prev, { event: 'error', data: e.message }]);
            setSyncing(false);
        }
    };

    const updateStatus = async (mapping, newStatus) => {
        try {
            const payload = {
                mappings: [
                    { ...mapping, status: newStatus }
                ]
            };
            const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/test-mapping`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                if (newStatus === 'REJECTED') {
                    setMappings(prev => prev.filter(m => !(m.product_symbol === mapping.product_symbol && m.test_symbol === mapping.test_symbol)));
                } else {
                    setMappings(prev => prev.map(m => 
                        (m.product_symbol === mapping.product_symbol && m.test_symbol === mapping.test_symbol) 
                        ? { ...m, status: newStatus } 
                        : m
                    ));
                }
            }
        } catch (e) {
            console.error("Failed to update status", e);
        }
    };

    const downloadTrainingData = async () => {
        try {
            const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/training-data?min_confidence=0.6&limit=5000&include_negatives=true`);
            if (res.ok) {
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `training-data-${projectId}-${Date.now()}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            } else {
                console.error("Failed to download training data");
            }
        } catch (e) {
            console.error("Failed to download training data", e);
        }
    };

    return (
        <div className="modal-overlay animate-in" style={{ backgroundColor: 'rgba(0,0,0,0.85)', zIndex: 1000 }}>
            <div className="glass" style={{ width: '90%', maxWidth: '1200px', height: '85vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ padding: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <Cpu size={20} color="var(--accent-blue)" />
                        <h3 style={{ margin: 0, color: 'var(--accent-blue)' }}>Interactive Code-to-Test Mapping Matrix</h3>
                    </div>
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                        <button onClick={downloadTrainingData} className="action-button secondary" style={{ fontSize: '0.875rem' }} disabled={mappings.length === 0}>
                            <Download size={16} /> Export CSV
                        </button>
                        
                        <button onClick={() => fetchMappings(0)} className="action-button secondary" style={{ fontSize: '0.875rem' }} disabled={syncing || syncConfiguring}>
                            <RefreshCw size={16} /> Refresh
                        </button>
                        
                        <button onClick={() => setSyncConfiguring(true)} disabled={syncing || syncConfiguring} className="action-button primary" style={{ fontSize: '0.875rem' }}>
                            <RefreshCw size={16} className={syncing ? "spin" : ""} /> {syncing ? 'Mapping Code...' : 'Run Mapping'}
                        </button>

                        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', marginLeft: '0.5rem' }}>
                            <X size={24} />
                        </button>
                    </div>
                </div>

                <div style={{ flex: 1, padding: '1.5rem', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                    {syncConfiguring ? (
                        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1.5rem', padding: '2rem' }}>
                            <Cpu size={48} style={{ color: 'var(--accent-blue)', opacity: 0.8 }} />
                            <h2 style={{ margin: 0 }}>Intelligence Mapping Pipeline</h2>
                            <p style={{ color: 'rgba(255,255,255,0.6)', textAlign: 'center', maxWidth: '400px', lineHeight: '1.5' }}>
                                This will use the Intelligence Engine to scan through all indexed ASTs and forge confidence edges between Production code and Test signatures.
                            </p>
                            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', background: 'rgba(255,255,255,0.05)', padding: '1.5rem', borderRadius: '1rem', border: '1px solid rgba(255,255,255,0.1)', marginTop: '0.5rem' }}>
                                <span style={{ color: 'rgba(255,255,255,0.8)', fontWeight: 600 }}>Engine:</span>
                                <select 
                                    value={llmModel} 
                                    onChange={(e) => setLlmModel && setLlmModel(e.target.value)}
                                    disabled={isLoadingModels}
                                    style={{ padding: '0.5rem 1rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(0,0,0,0.4)', color: 'white', outline: 'none', cursor: 'pointer', minWidth: '200px' }}
                                >
                                    <option value="">Repo-Native (Structural Only)</option>
                                    {fetchedModels?.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
                                </select>
                            </div>
                            {serverFeatures?.vector_matching && (
                                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', background: 'rgba(255,255,255,0.05)', padding: '1rem 1.5rem', borderRadius: '1rem', border: '1px solid rgba(255,255,255,0.1)' }}>
                                    <Zap size={18} style={{ color: useVector ? 'var(--accent-green)' : 'rgba(255,255,255,0.4)' }} />
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                        <input 
                                            type="checkbox" 
                                            checked={useVector}
                                            onChange={(e) => setUseVector(e.target.checked)}
                                            style={{ width: '18px', height: '18px', accentColor: 'var(--accent-green)' }}
                                        />
                                        <span style={{ color: useVector ? 'var(--accent-green)' : 'rgba(255,255,255,0.7)' }}>Vector Matching (Embeddings)</span>
                                    </label>
                                </div>
                            )}
                            {!serverFeatures?.vector_matching && (
                                <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
                                    Build with core-ml profile to enable Vector Matching
                                </p>
                            )}
                            <div style={{ background: 'rgba(255,255,255,0.05)', padding: '1.5rem', borderRadius: '1rem', border: '1px solid rgba(255,255,255,0.1)', marginTop: '1rem' }}>
                                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem' }}>
                                    <Cpu size={18} style={{ color: useInstrumentation ? 'var(--accent-blue)' : 'rgba(255,255,255,0.4)' }} />
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                        <input 
                                            type="checkbox" 
                                            checked={useInstrumentation}
                                            onChange={(e) => {
                                                setUseInstrumentation(e.target.checked);
                                                if (e.target.checked && !testRepoUrl && autoRepoUrl) {
                                                    setTestRepoUrl(autoRepoUrl);
                                                }
                                            }}
                                            style={{ width: '18px', height: '18px', accentColor: 'var(--accent-blue)' }}
                                        />
                                        <span style={{ color: useInstrumentation ? 'var(--accent-blue)' : 'rgba(255,255,255,0.7)', fontWeight: 600 }}>Runtime Instrumentation (Coverage-Based)</span>
                                    </label>
                                </div>
                                {useInstrumentation && (
                                    <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                                            <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.875rem', minWidth: '120px' }}>Test Repository:</span>
                                            <input 
                                                type="text" 
                                                value={testRepoUrl}
                                                onChange={(e) => setTestRepoUrl(e.target.value)}
                                                placeholder={autoRepoUrl || "https://github.com/owner/repo"}
                                                style={{ 
                                                    flex: 1,
                                                    padding: '0.5rem 1rem', 
                                                    borderRadius: '0.5rem', 
                                                    border: '1px solid rgba(255,255,255,0.2)', 
                                                    background: 'rgba(0,0,0,0.4)', 
                                                    color: 'white', 
                                                    outline: 'none',
                                                    fontSize: '0.875rem'
                                                }}
                                            />
                                        </div>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                            <input 
                                                type="checkbox" 
                                                checked={runFresh}
                                                onChange={(e) => setRunFresh(e.target.checked)}
                                                style={{ width: '16px', height: '16px', accentColor: 'var(--accent-blue)' }}
                                            />
                                            <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.875rem' }}>Run fresh (don't use cached results)</span>
                                        </label>
                                        <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.75rem', margin: 0 }}>
                                            Uses pytest-cov to instrument tests and build precise test-to-symbol mapping
                                        </p>
                                    </div>
                                )}
                            </div>
                            <div style={{ display: 'flex', gap: '1.5rem', marginTop: '1rem' }}>
                                <button onClick={() => setSyncConfiguring(false)} className="action-button secondary" style={{ padding: '0.75rem 2.5rem' }}>Cancel</button>
                                <button onClick={startSyncProcess} className="action-button primary" style={{ padding: '0.75rem 2.5rem' }}>
                                    {useInstrumentation ? 'Run Instrumentation' : llmModel ? 'Begin AI Boost' : useVector ? 'Run Vector Map' : 'Run Structural Map'}
                                </button>
                            </div>
                        </div>
                    ) : (syncing || (syncLogs.length > 0 && mappings.length === 0)) ? (
                        <div style={{ flex: 1, background: '#0d1117', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '1rem', minHeight: '300px', overflowY: 'auto', fontFamily: 'monospace', color: '#c9d1d9', fontSize: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                            {syncLogs.map((log, idx) => (
                                <div key={idx} style={{ 
                                    color: log.event === 'error' ? '#ff7b72' : log.event === 'reasoning' ? '#a5d6ff' : '#c9d1d9',
                                    animation: 'fadeIn 0.3s ease-out'
                                }}>
                                    <span style={{ opacity: 0.5 }}>{new Date().toLocaleTimeString()}</span> &nbsp;
                                    {log.event === 'error' ? '❌ ' : '⚡ '} 
                                    {typeof log.data === 'string' ? log.data : JSON.stringify(log.data)}
                                </div>
                            ))}
                            {syncing && (
                                <div style={{ color: 'rgba(255,255,255,0.4)', marginTop: '1rem', fontStyle: 'italic' }}>
                                    <span className="pulse">●</span> Intelligence processing...
                                </div>
                            )}
                        </div>
                    ) : loading ? (
                        <div style={{ textAlign: 'center', padding: '2rem', color: 'rgba(255,255,255,0.5)' }}>Loading mappings...</div>
                    ) : mappings.length === 0 && !searchTerm && activeTab === 'coverage' ? (
                        <div style={{ textAlign: 'center', padding: '4rem', color: 'rgba(255,255,255,0.4)' }}>
                            <Cpu size={32} style={{ marginBottom: '1rem', opacity: 0.5, display: 'inline-block' }} />
                            <p>No instrumentation data. Run instrumentation first.</p>
                            {onOpenInstrumentation && (
                                <button onClick={onOpenInstrumentation} className="action-button primary" style={{ marginTop: '1rem', padding: '0.75rem 2rem' }}>
                                    Run Instrumentation
                                </button>
                            )}
                        </div>
                    ) : mappings.length === 0 && !searchTerm ? (
                        <div style={{ textAlign: 'center', padding: '4rem', color: 'rgba(255,255,255,0.4)' }}>
                            <Search size={32} style={{ marginBottom: '1rem', opacity: 0.5, display: 'inline-block' }} />
                            <p>No mappings found in the Neo4j database. <br/>Click "Map via AI" to use Intelligence Engine to forge connections.</p>
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '0.5rem' }}>
                                {['all', 'structural', 'llm', 'vector', 'coverage'].map(tab => (
                                    <button
                                        key={tab}
                                        onClick={() => handleTabChange(tab)}
                                        style={{
                                            padding: '0.5rem 1rem',
                                            background: activeTab === tab ? 'rgba(255,255,255,0.1)' : 'transparent',
                                            border: 'none',
                                            borderRadius: '0.5rem 0.5rem 0 0',
                                            color: activeTab === tab ? 'var(--accent-blue)' : 'rgba(255,255,255,0.5)',
                                            cursor: 'pointer',
                                            fontSize: '0.875rem',
                                            fontWeight: activeTab === tab ? 600 : 400,
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        {tab === 'all' ? 'All' : tab === 'structural' ? 'Structural' : tab === 'llm' ? 'LLM' : tab === 'vector' ? 'Vector' : 'Coverage-Based'}
                                    </button>
                                ))}
                            </div>
                            <div style={{ position: 'relative' }}>
                                <Search size={18} style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.4)' }} />
                                <input 
                                    type="text" 
                                    placeholder="Search by product symbol or file path..." 
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    style={{ 
                                        width: '100%', 
                                        padding: '0.75rem 1rem 0.75rem 3rem', 
                                        borderRadius: '0.75rem', 
                                        background: 'rgba(255,255,255,0.05)', 
                                        border: '1px solid rgba(255,255,255,0.1)', 
                                        color: 'white', 
                                        outline: 'none'
                                    }}
                                />
                            </div>
                            
                            <div style={{ overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                                <thead>
                                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.5)', textAlign: 'left' }}>
                                        <th style={{ padding: '1rem 0' }}>Product Symbol</th>
                                        <th>Test Symbol</th>
                                        <th>Reasoning</th>
                                        <th>Status</th>
                                        <th style={{ textAlign: 'right' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {mappings.map((m, idx) => (
                                        <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: m.status === 'APPROVED_TEST' ? 'rgba(0, 255, 128, 0.05)' : 'transparent' }}>
                                            <td style={{ padding: '1rem 0', verticalAlign: 'top', width: '20%' }}>
                                                <div style={{ fontWeight: 600, color: 'rgba(255,255,255,0.9)', marginBottom: '0.25rem' }}>{m.product_symbol}</div>
                                                <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)' }}>{m.product_file}</div>
                                            </td>
                                            <td style={{ verticalAlign: 'top', paddingTop: '1rem', width: '20%' }}>
                                                <div style={{ fontWeight: 600, color: '#a5d6ff', marginBottom: '0.25rem' }}>{m.test_symbol}</div>
                                                <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)' }}>{m.test_file}</div>
                                            </td>
                                            <td style={{ verticalAlign: 'top', paddingTop: '1rem', width: '30%', color: 'rgba(255,255,255,0.6)', lineHeight: '1.4' }}>
                                                {m.reasoning}
                                            </td>
                                            <td style={{ verticalAlign: 'top', paddingTop: '1rem', width: '15%' }}>
                                                <span style={{ 
                                                    padding: '0.25rem 0.5rem', 
                                                    borderRadius: '1rem', 
                                                    fontSize: '0.75rem',
                                                    background: m.status === 'APPROVED_TEST' ? 'rgba(0, 255, 128, 0.1)' : 'rgba(255, 160, 0, 0.1)',
                                                    color: m.status === 'APPROVED_TEST' ? '#4caf50' : '#ffa000'
                                                }}>
                                                    {m.status.replace('_TEST', '')}
                                                </span>
                                            </td>
                                            <td style={{ verticalAlign: 'top', paddingTop: '1rem', textAlign: 'right', width: '15%' }}>
                                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                                                    {m.status !== 'APPROVED_TEST' && (
                                                        <button onClick={() => updateStatus(m, 'APPROVED_TEST')} className="action-button primary" style={{ padding: '0.4rem 0.75rem', fontSize: '0.75rem', gap: '0.25rem' }}>
                                                            <CheckCircle size={14} /> Approve
                                                        </button>
                                                    )}
                                                    <button onClick={() => updateStatus(m, 'REJECTED')} className="action-button secondary" style={{ padding: '0.4rem 0.75rem', fontSize: '0.75rem', gap: '0.25rem' }}>
                                                        <XCircle size={14} /> Reject
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {hasMore && (
                                <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                                    <button 
                                        onClick={() => fetchMappings(offset + LIMIT)} 
                                        className="action-button secondary"
                                        style={{ padding: '0.75rem 2rem' }}
                                    >
                                        Load More Mappings
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                )}
                </div>
            </div>
        </div>
    );
};

export default TestMappingMatrix;
