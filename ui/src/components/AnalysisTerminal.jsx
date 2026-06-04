import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Send, X, Cpu, CheckCircle, AlertCircle, Play, ChevronRight, MessageSquare, ExternalLink, Activity, Code } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import API_BASE from '../config';
import Mermaid from './Mermaid';

const AnalysisTerminal = ({ runId, projectId, onClose, initialEvents = [], mode = 'streaming' }) => {
    const [events, setEvents] = useState(initialEvents);
    const [status, setStatus] = useState(mode === 'replay' ? 'completed' : 'initializing');
    const scrollRef = useRef(null);

    useEffect(() => {
        if (mode === 'replay') {
            setEvents(initialEvents);
            const lastStatusEvent = [...initialEvents].reverse().find(e => e.event === 'status');
            if (lastStatusEvent) {
                setStatus(lastStatusEvent.data.status.toLowerCase());
            } else {
                setStatus('completed');
            }
        }
    }, [initialEvents, mode]);

    useEffect(() => {
        if (mode === 'replay') return;

        const eventSource = new EventSource(`${API_BASE}/projects/${projectId}/runs/${runId}/stream`);

        eventSource.onmessage = (event) => {
            const parsed = JSON.parse(event.data);
            setEvents(prev => [...prev, parsed]);

            if (parsed.event === 'status') {
                setStatus(parsed.data.status.toLowerCase());
                if (parsed.data.status === 'COMPLETED' || parsed.data.status === 'FAILED') {
                    // Let the server close the connection naturally to ensure background persistence completes
                }
            }
        };

        eventSource.onerror = (err) => {
            console.error('SSE Error:', err);
            setEvents(prev => [...prev, { event: 'error', data: 'Connection to analysis stream lost.' }]);
            eventSource.close();
            setStatus('failed');
        };

        return () => eventSource.close();
    }, [runId, projectId, mode]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [events]);

    const handleAction = (type) => {
        alert(`Action "${type}" triggered. In the final version, this will open the PR, run tests on the sandbox, or show detailed reports.`);
        // Placeholder for real actions
    };

    return (
        <div className="modal-overlay animate-in" style={{ backgroundColor: 'rgba(0,0,0,0.85)', zIndex: 1000 }}>
            <div className="glass" style={{ 
                width: '90%', 
                maxWidth: '1000px', 
                height: '80vh', 
                display: 'flex', 
                flexDirection: 'column',
                overflow: 'hidden',
                border: '1px solid rgba(255,255,255,0.1)'
            }}>
                {/* Header */}
                <div style={{ padding: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(0,0,0,0.2)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div className={`status-indicator ${status}`} />
                        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-blue)' }}>
                            <Cpu size={20} /> {mode === 'replay' ? 'Analysis Replay' : 'Analysis Terminal'} (Run #{runId})
                        </h3>
                    </div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                        <X size={24} />
                    </button>
                </div>

                {/* Event Feed */}
                <div ref={scrollRef} style={{ flex: 1, padding: '1.5rem', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {events.length === 0 && status !== 'running' && (
                        <div style={{ padding: '2rem', textAlign: 'center', color: 'rgba(255,255,255,0.3)' }}>
                            <Activity size={32} style={{ marginBottom: '1rem', opacity: 0.2 }} />
                            <p>No events were persisted for this run.</p>
                        </div>
                    )}
                    {events.map((ev, idx) => (
                        <div key={idx} className="animate-in" style={{ 
                            display: 'flex', 
                            flexDirection: 'column',
                            gap: '0.5rem'
                        }}>
                            {renderEvent(ev)}
                        </div>
                    ))}
                    {status === 'running' && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'rgba(255,255,255,0.4)', fontSize: '0.875rem' }}>
                            <div className="spinner" style={{ width: '12px', height: '12px' }} /> LLM is thinking...
                        </div>
                    )}
                </div>

                {/* PR Actions Bar */}
                <div style={{ padding: '1.5rem', borderTop: '1px solid rgba(255,255,255,0.1)', background: 'rgba(0,0,0,0.3)', display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.875rem', color: 'rgba(255,255,255,0.4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>PR Actions:</span>
                    <button onClick={() => handleAction('open_pr')} className="action-button secondary" style={{ fontSize: '0.875rem', gap: '0.5rem' }}>
                        <ExternalLink size={16} /> Open PR
                    </button>
                    <button onClick={() => handleAction('run_tests')} className="action-button secondary" style={{ fontSize: '0.875rem', gap: '0.5rem' }}>
                        <Activity size={16} /> Run Execution
                    </button>
                    <button onClick={() => handleAction('view_results')} className="action-button secondary" style={{ fontSize: '0.875rem', gap: '0.5rem' }}>
                        <Code size={16} /> View Results
                    </button>
                </div>
            </div>
        </div>
    );
};

const renderEvent = (ev) => {
    switch (ev.event) {
        case 'status':
            return (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'rgba(255,255,255,0.4)', fontSize: '0.8125rem', padding: '0.5rem 0', borderTop: '1px solid rgba(255,255,255,0.03)' }}>
                    <Activity size={14} />
                    <span>Status changed to: <strong style={{ color: 'var(--accent-blue)' }}>{ev.data.status}</strong></span>
                </div>
            );
        case 'reasoning':
            return (
                <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
                    <div style={{ padding: '0.25rem', color: 'var(--accent-blue)', flexShrink: 0 }}><MessageSquare size={16} /></div>
                    <div style={{ color: 'rgba(255,255,255,0.9)', lineHeight: '1.6', fontSize: '0.95rem', width: '100%' }}>
                        <ReactMarkdown
                            components={{
                                code({ node, inline, className, children, ...props }) {
                                    const match = /language-(\w+)/.exec(className || '');
                                    
                                    // Safely extract string content from children array or element
                                    const extractText = (childArray) => {
                                        if (typeof childArray === 'string') return childArray;
                                        if (Array.isArray(childArray)) return childArray.map(extractText).join('');
                                        return '';
                                    };
                                    
                                    const codeText = extractText(children).replace(/\n$/, '');

                                    return !inline && match && match[1] === 'mermaid' ? (
                                        <Mermaid chart={codeText} />
                                    ) : (
                                        <code className={className} {...props}>
                                            {children}
                                        </code>
                                    );
                                },
                                h1: ({node, ...props}) => <h1 style={{fontSize: '1.25rem', marginTop: '1rem', marginBottom: '0.5rem', color: 'var(--accent-blue)'}} {...props} />,
                                h2: ({node, ...props}) => <h2 style={{fontSize: '1.1rem', marginTop: '1rem', marginBottom: '0.5rem', borderBottom: '1px solid rgba(255,255,255,0.1)'}} {...props} />,
                                h3: ({node, ...props}) => <h3 style={{fontSize: '1rem', marginTop: '1rem', marginBottom: '0.5rem'}} {...props} />,
                                p: ({node, ...props}) => <p style={{marginBottom: '0.75rem'}} {...props} />,
                                li: ({node, ...props}) => <li style={{marginBottom: '0.4rem'}} {...props} />,
                                a: ({node, ...props}) => <a target="_blank" rel="noopener noreferrer" style={{color: 'var(--accent-blue)', textDecoration: 'underline'}} {...props} />
                            }}
                        >
                            {ev.data}
                        </ReactMarkdown>
                    </div>
                </div>
            );
        case 'tool_call':
            return (
                <div style={{ 
                    background: 'rgba(255,255,255,0.03)', 
                    borderRadius: '0.75rem', 
                    borderLeft: '4px solid var(--accent-blue)',
                    padding: '1rem',
                    fontFamily: 'monospace',
                    fontSize: '0.875rem'
                }}>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>
                        <Terminal size={14} /> TOOL CALL: {ev.data.tool}
                    </div>
                    <pre style={{ margin: 0, overflowX: 'auto', color: '#a5d6ff' }}>{ev.data.code}</pre>
                </div>
            );
        case 'log':
            return (
                <div style={{ paddingLeft: '2.25rem', color: 'rgba(255,255,255,0.5)', fontSize: '0.875rem', fontFamily: 'monospace' }}>
                    <span style={{ color: 'var(--accent-blue)' }}>&gt;</span> {ev.data}
                </div>
            );
        case 'suggestion':
            return (
                <div style={{ 
                    background: 'rgba(0,100,255,0.1)', 
                    borderRadius: '1rem', 
                    padding: '1.25rem', 
                    border: '1px solid rgba(0,100,255,0.2)',
                    marginTop: '0.5rem'
                }}>
                    <p style={{ margin: '0 0 1rem 0', fontWeight: 500 }}>{ev.data.text}</p>
                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                        {ev.data.actions.map((act, i) => (
                            <button 
                                key={i} 
                                className="action-button secondary" 
                                onClick={() => alert(`Dynamic Action: ${act.label}`)}
                                style={{ fontSize: '0.875rem', background: 'rgba(255,255,255,0.1)' }}
                            >
                                {act.label}
                            </button>
                        ))}
                    </div>
                </div>
            );
        case 'error':
            return (
                <div style={{ color: 'var(--accent-red)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem' }}>
                    <AlertCircle size={16} /> {ev.data}
                </div>
            );
        default:
            return null;
    }
};

export default AnalysisTerminal;
