import React, { useState, useEffect } from 'react';
import { useGithub } from '../contexts/GithubProvider';
import { X, Save, Plus, Trash2, Sparkles } from 'lucide-react';
import API_BASE from '../config';

const StyleCapsuleManager = ({ isOpen, onClose, projectId, automationRepoName, availableModels = [], selectedModel, onModelChange }) => {
    const { fetchWithGithub } = useGithub();
    const [capsule, setCapsule] = useState({
        framework: 'pytest',
        foundational_patterns: {},
        negative_patterns: [],
        reference_examples: []
    });
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (isOpen) {
            fetchCapsule();
        }
    }, [isOpen]);

    const fetchCapsule = async () => {
        setLoading(true);
        try {
            const response = await fetchWithGithub(`${API_BASE}/projects/${projectId}/style-capsule`);
            if (response.ok) {
                const data = await response.json();
                setCapsule(data);
            }
        } catch (error) {
            console.error('Failed to fetch capsule:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSync = async () => {
        if (!automationRepoName) return;
        setLoading(true);
        try {
            const provider = localStorage.getItem('llm_provider') || 'Google';
            const response = await fetchWithGithub(`${API_BASE}/projects/${projectId}/sync-style`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    full_repo_name: automationRepoName,
                    provider_name: provider,
                    model_name: selectedModel
                })
            });
            if (response.ok) {
                const data = await response.json();
                if (data.status === 'syncing') {
                    // Success! It's happening in background.
                    // We'll wait a bit and refresh.
                    setTimeout(fetchCapsule, 10000); // 10s is usually enough for Gemini
                } else {
                    setCapsule(data);
                }
            } else {
                alert("Failed to sync style from repo. Make sure TESTING_STANDARDS.md exists.");
            }
        } catch (error) {
            console.error('Failed to sync capsule:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        setLoading(true);
        try {
            const response = await fetchWithGithub(`${API_BASE}/projects/${projectId}/style-capsule`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(capsule)
            });
            if (response.ok) {
                onClose();
            }
        } catch (error) {
            console.error('Failed to save capsule:', error);
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="manager-overlay" onClick={onClose}>
            <div className="glass manager-panel animate-in" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '36rem' }}>
                <div className="panel-header" style={{ alignItems: 'flex-start' }}>
                    <div>
                        <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Style Capsule Manager</h2>
                        <p style={{ fontSize: '0.8125rem', color: 'rgba(255,255,255,0.4)', marginTop: '0.25rem' }}>
                            Define the patterns and snippets for generated tests.
                        </p>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                        {automationRepoName && (
                            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', background: 'rgba(255,255,255,0.03)', padding: '0.25rem 0.5rem', borderRadius: '0.75rem', border: '1px solid rgba(255,255,255,0.05)' }}>
                                <span style={{ fontSize: '0.7rem', opacity: 0.4, textTransform: 'uppercase', letterSpacing: '0.02em' }}>Model</span>
                                <select 
                                    value={selectedModel}
                                    onChange={(e) => onModelChange(e.target.value)}
                                    style={{ 
                                        padding: '0.35rem 1.6rem 0.35rem 0.5rem', 
                                        fontSize: '0.75rem', 
                                        borderRadius: '0.5rem',
                                        background: 'none',
                                        border: 'none',
                                        color: 'white',
                                        cursor: 'pointer',
                                        fontWeight: 600
                                    }}
                                >
                                    {availableModels.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
                                </select>
                                <button 
                                    onClick={handleSync}
                                    disabled={loading}
                                    className={`action-button ${loading ? 'loading' : ''}`}
                                    style={{ 
                                        background: 'rgba(56, 189, 248, 0.1)', 
                                        color: 'var(--accent-blue)', 
                                        fontSize: '0.75rem',
                                        padding: '0.4rem 0.8rem',
                                        minWidth: '110px'
                                    }}
                                >
                                    {loading ? (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                            <div className="spinner-small" /> <span>Syncing...</span>
                                        </div>
                                    ) : (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                            <Sparkles size={14} /> <span>Sync from Repo</span>
                                        </div>
                                    )}
                                </button>
                            </div>
                        )}
                        <button onClick={onClose} style={{ padding: '0.5rem', opacity: 0.5 }}>
                            <X size={24} />
                        </button>
                    </div>
                </div>

                <div className="panel-content">
                    <Section title="Framework Configuration">
                        <select
                            value={capsule.framework}
                            onChange={(e) => setCapsule({ ...capsule, framework: e.target.value })}
                            style={{ width: '100%' }}
                        >
                            <option value="pytest">pytest</option>
                            <option value="unittest">unittest</option>
                            <option value="playwright">playwright</option>
                        </select>
                    </Section>

                    <Section title="Negative Patterns" description="Patterns the LLM should strictly avoid.">
                        <TagInput
                            tags={capsule.negative_patterns}
                            onTagsChange={(tags) => setCapsule({ ...capsule, negative_patterns: tags })}
                            placeholder="e.g., hardcoded_secrets, avoid_print"
                        />
                    </Section>

                    <Section title="Reference Examples" description="High-quality snippets for few-shot learning.">
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {capsule.reference_examples.map((ex, i) => (
                                <div key={i} className="example-card">
                                    <button
                                        onClick={() => {
                                            const newEx = [...capsule.reference_examples];
                                            newEx.splice(i, 1);
                                            setCapsule({ ...capsule, reference_examples: newEx });
                                        }}
                                        style={{ position: 'absolute', top: '1rem', right: '1rem', color: '#f87171' }}
                                    >
                                        <Trash2 size={16} />
                                    </button>
                                    <input
                                        value={ex.name}
                                        onChange={(e) => {
                                            const newEx = [...capsule.reference_examples];
                                            newEx[i].name = e.target.value;
                                            setCapsule({ ...capsule, reference_examples: newEx });
                                        }}
                                        style={{ width: '100%', background: 'none', border: 'none', padding: 0, marginBottom: '0.5rem', fontWeight: 600, color: 'var(--accent-blue)' }}
                                        placeholder="Example Name"
                                    />
                                    <textarea
                                        value={ex.code}
                                        onChange={(e) => {
                                            const newEx = [...capsule.reference_examples];
                                            newEx[i].code = e.target.value;
                                            setCapsule({ ...capsule, reference_examples: newEx });
                                        }}
                                        style={{ width: '100%', minHeight: '100px', fontSize: '0.875rem', fontFamily: 'monospace' }}
                                        placeholder="Paste code snippet here..."
                                    />
                                </div>
                            ))}
                            <button
                                onClick={() => setCapsule({ ...capsule, reference_examples: [...capsule.reference_examples, { name: '', code: '' }] })}
                                style={{ width: '100%', border: '1px dashed rgba(255,255,255,0.2)', borderRadius: '1rem', padding: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}
                            >
                                <Plus size={16} />
                                <span>Add Example</span>
                            </button>
                        </div>
                    </Section>
                </div>

                <div style={{ paddingTop: '2rem', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                    <button
                        onClick={handleSave}
                        disabled={loading}
                        className="save-button"
                    >
                        <Save size={20} />
                        <span>{loading ? 'Saving...' : 'Save Style Capsule'}</span>
                    </button>
                </div>
            </div>
        </div>
    );
};

const Section = ({ title, description, children }) => (
    <div className="section">
        <div className="section-header">
            <h3 className="section-title">{title}</h3>
            {description && <p className="section-desc">{description}</p>}
        </div>
        {children}
    </div>
);

const TagInput = ({ tags, onTagsChange, placeholder }) => {
    const [input, setInput] = useState('');

    const addTag = () => {
        if (input && !tags.includes(input)) {
            onTagsChange([...tags, input]);
            setInput('');
        }
    };

    return (
        <div className="tag-input-wrapper">
            <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addTag()}
                    style={{ flex: 1 }}
                    placeholder={placeholder}
                />
                <button onClick={addTag} style={{ background: 'rgba(255,255,255,0.05)', padding: '0 1rem', borderRadius: '0.5rem' }}>
                    <Plus size={20} />
                </button>
            </div>
            <div className="tag-container">
                {tags.map((tag, i) => (
                    <span key={i} className="tag">
                        {tag}
                        <X size={12} style={{ cursor: 'pointer' }} onClick={() => onTagsChange(tags.filter(t => t !== tag))} />
                    </span>
                ))}
            </div>
        </div>
    );
};

export default StyleCapsuleManager;
