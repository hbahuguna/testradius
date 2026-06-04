import React, { useState, useEffect } from 'react';
import { X, Server } from 'lucide-react';
import { useGithub } from '../contexts/GithubProvider';

const SyncModal = ({ title, desc, endpoint, payload, onClose }) => {
    const { fetchWithGithub } = useGithub();
    const [logs, setLogs] = useState([]);
    const [status, setStatus] = useState('starting');

    useEffect(() => {
        let isCancelled = false;
        
        const runSync = async () => {
            try {
                const res = await fetchWithGithub(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: payload ? JSON.stringify(payload) : undefined
                });
                
                if (!res.ok) throw new Error("Sync API request failed. Status: " + res.status);
                
                const contentType = res.headers.get('content-type');
                if (contentType && contentType.includes('text/event-stream')) {
                    const reader = res.body.getReader();
                    const decoder = new TextDecoder();
                    while (!isCancelled) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        const text = decoder.decode(value);
                        const parts = text.split('\n\n');
                        for (let line of parts) {
                            if (line.startsWith('data: ')) {
                                try {
                                    const payloadDoc = JSON.parse(line.replace('data: ', ''));
                                    if (payloadDoc.event === 'status') {
                                        if (!isCancelled) {
                                            setStatus(payloadDoc.data.status === 'COMPLETED' ? 'success' : 'failed');
                                        }
                                        if (payloadDoc.data.status === 'COMPLETED') return;
                                    } else {
                                        if (!isCancelled) {
                                            setLogs(prev => [...prev, { 
                                                type: payloadDoc.event, 
                                                content: payloadDoc.data,
                                                timestamp: new Date().toLocaleTimeString()
                                            }]);
                                        }
                                    }
                                } catch(e){}
                            }
                        }
                    }
                } else {
                    const data = await res.json();
                    if (!isCancelled) {
                        setLogs([{ 
                            type: 'status', 
                            content: data.message || "Sync completed successfully!",
                            timestamp: new Date().toLocaleTimeString()
                        }]);
                        setStatus('success');
                    }
                }
            } catch (e) {
                if (!isCancelled) {
                    setLogs(prev => [...prev, { 
                        type: 'error', 
                        content: e.message,
                        timestamp: new Date().toLocaleTimeString()
                    }]);
                    setStatus('failed');
                }
            }
        };
        runSync();
        return () => { isCancelled = true; };
    }, [endpoint]);

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
                        <Server size={20} color="var(--accent-blue)" className={status === 'starting' ? "pulse" : ""} />
                        <h3 style={{ margin: 0, color: 'var(--accent-blue)' }}>{title}</h3>
                    </div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                        <X size={24} />
                    </button>
                </div>
                
                <div style={{ padding: '1rem 1.5rem', background: 'rgba(0,0,0,0.2)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <p style={{ margin: 0, color: 'rgba(255,255,255,0.7)', fontSize: '0.875rem' }}>{desc}</p>
                </div>

                <div style={{ flex: 1, padding: '1rem', background: '#0a0c10', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {logs.length === 0 && status === 'starting' && (
                        <div style={{ color: 'rgba(255,255,255,0.4)', fontStyle: 'italic', padding: '1rem' }}>
                            <span className="pulse">●</span> Initiating background job...
                        </div>
                    )}
                    {logs.map((log, idx) => (
                        <div key={idx} style={{ 
                            color: log.type === 'error' ? '#ff7b72' : log.type === 'reasoning' ? '#a5d6ff' : '#c9d1d9',
                            animation: 'fadeIn 0.3s ease-out'
                        }}>
                            <span style={{ opacity: 0.5 }}>{log.timestamp}</span> &nbsp;
                            {log.type === 'error' ? '❌ ' : log.type === 'status' ? '✅ ' : '⚡ '} 
                            {typeof log.content === 'string' ? log.content : JSON.stringify(log.content)}
                        </div>
                    ))}
                    {status === 'starting' && logs.length > 0 && (
                        <div style={{ color: 'rgba(255,255,255,0.4)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                            <span className="pulse">●</span> Processing tree hierarchies...
                        </div>
                    )}
                    {status === 'success' && (
                        <div style={{ color: '#4caf50', marginTop: '1rem', fontWeight: 600 }}>✨ AST Ingestion Pipeline Completed !</div>
                    )}
                </div>
            </div>
        </div>
    );
};
export default SyncModal;
