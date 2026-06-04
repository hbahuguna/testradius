import React from 'react';
import { History, Clock, CheckCircle, AlertCircle, Play, ChevronRight, Cpu } from 'lucide-react';

const RunHistory = ({ runs, onSelectRun }) => {
    if (!runs || runs.length === 0) {
        return (
            <div className="glass" style={{ padding: '2rem', textAlign: 'center', borderRadius: '1.5rem', marginTop: '1.5rem', opacity: 0.6 }}>
                <History size={32} style={{ marginBottom: '1rem', opacity: 0.3 }} />
                <p>No past analysis runs for this PR.</p>
            </div>
        );
    }

    return (
        <div style={{ marginTop: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                <History size={20} style={{ color: 'var(--accent-blue)' }} />
                <h3 style={{ margin: 0, fontSize: '1.125rem' }}>Analysis History</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {runs.map(run => (
                    <div 
                        key={run.id} 
                        className="glass example-card animate-in" 
                        onClick={() => onSelectRun(run)}
                        style={{ 
                            padding: '1.25rem 1.5rem', 
                            cursor: 'pointer', 
                            display: 'flex', 
                            alignItems: 'center', 
                            justifyContent: 'space-between',
                            border: '1px solid rgba(255,255,255,0.05)',
                            borderRadius: '1.25rem',
                            transition: 'all 0.2s ease',
                            background: 'rgba(255,255,255,0.02)'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
                        onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.02)'}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                            <div className={`status-indicator ${run.status.toLowerCase()}`} />
                            <div>
                                <div style={{ fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
                                    Run #{run.id}
                                    <div style={{ 
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.35rem',
                                        fontSize: '0.75rem', 
                                        background: 'rgba(56, 189, 248, 0.1)', 
                                        padding: '0.2rem 0.6rem', 
                                        borderRadius: '99px',
                                        color: 'var(--accent-blue)',
                                        fontWeight: 600,
                                        border: '1px solid rgba(56, 189, 248, 0.2)'
                                    }}>
                                        <Cpu size={12} />
                                        {run.run_metadata?.llm_model || 'gemini-1.5-flash-latest'}
                                    </div>
                                </div>
                                <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', opacity: 0.8 }}>
                                    <Clock size={12} /> {new Date(run.created_at).toLocaleString()}
                                </div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
                            <span style={{ 
                                fontSize: '0.7rem', 
                                fontWeight: 800, 
                                opacity: 0.8, 
                                textTransform: 'uppercase', 
                                letterSpacing: '0.05em',
                                color: run.status === 'COMPLETED' ? '#10b981' : run.status === 'FAILED' ? '#ef4444' : 'var(--accent-blue)'
                            }}>
                                {run.status}
                            </span>
                            <ChevronRight size={18} style={{ opacity: 0.3 }} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default RunHistory;
