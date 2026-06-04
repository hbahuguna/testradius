import React, { useState, useEffect } from 'react';
import { X, CheckCircle, Github, Cpu } from 'lucide-react';

const SettingsModal = ({ isOpen, onClose, onOpenFeatureManager }) => {
    const [activeTab, setActiveTab] = useState('github');

    // GitHub State
    const [ghToken, setGhToken] = useState('');
    const [ghStatus, setGhStatus] = useState(null); // 'success', 'error', 'testing'

    // LLM State
    const [llmProvider, setLlmProvider] = useState('Google');
    const [llmKey, setLlmKey] = useState('');
    const [llmModel, setLlmModel] = useState('');
    const [llmStatus, setLlmStatus] = useState(null);

    useEffect(() => {
        if (isOpen) {
            // Load from localStorage
            setGhToken(localStorage.getItem('gh_provider_token') || '');
            setLlmProvider(localStorage.getItem('llm_provider') || 'Google');
            setLlmKey(localStorage.getItem('llm_api_key') || '');
            setLlmModel(localStorage.getItem('llm_default_model') || '');
            
            setGhStatus(null);
            setLlmStatus(null);
        }
    }, [isOpen]);

    const handleSaveGithub = async () => {
        setGhStatus('testing');
        try {
            const res = await fetch('https://api.github.com/user', {
                headers: { 'Authorization': `token ${ghToken}` }
            });
            if (res.ok) {
                localStorage.setItem('gh_provider_token', ghToken);
                setGhStatus('success');
                window.dispatchEvent(new Event('gh-token-updated'));
            } else {
                setGhStatus('error');
            }
        } catch (e) {
            setGhStatus('error');
        }
    };

    const handleSaveLLM = () => {
        localStorage.setItem('llm_provider', llmProvider);
        localStorage.setItem('llm_api_key', llmKey);
        localStorage.setItem('llm_default_model', llmModel);
        setLlmStatus('success');
        window.dispatchEvent(new Event('llm-settings-updated'));
        setTimeout(() => setLlmStatus(null), 3000);
    };

    if (!isOpen) return null;

    return (
        <div className="modal-overlay animate-in" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
            <div className="glass modal-content" style={{ width: '600px', padding: 0, overflow: 'hidden' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1.5rem', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <SettingsIcon /> User Configuration
                    </h2>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                        <X size={24} />
                    </button>
                </div>

                <div style={{ display: 'flex' }}>
                    {/* Sidebar Tabs */}
                    <div style={{ width: '200px', borderRight: '1px solid rgba(255,255,255,0.1)', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <button
                            onClick={() => setActiveTab('github')}
                            className={`action-button ${activeTab === 'github' ? 'primary' : ''}`}
                            style={{ justifyContent: 'flex-start', border: activeTab !== 'github' ? 'none' : undefined, background: activeTab !== 'github' ? 'transparent' : undefined }}
                        >
                            <Github size={18} /> GitHub Integrations
                        </button>
                        <button
                            onClick={() => setActiveTab('llm')}
                            className={`action-button ${activeTab === 'llm' ? 'primary' : ''}`}
                            style={{ justifyContent: 'flex-start', border: activeTab !== 'llm' ? 'none' : undefined, background: activeTab !== 'llm' ? 'transparent' : undefined }}
                        >
                            <Cpu size={18} /> AI Providers
                        </button>
                        <button
                            onClick={() => onOpenFeatureManager?.()}
                            className="action-button"
                            style={{ justifyContent: 'flex-start', border: 'none', background: 'transparent', marginTop: '1rem' }}
                        >
                            Manage Features
                        </button>
                    </div>

                    {/* Content Area */}
                    <div style={{ flex: 1, padding: '2rem' }}>

                        {activeTab === 'github' && (
                            <div className="animate-in">
                                <h3>GitHub Access Token</h3>
                                <p style={{ fontSize: '0.875rem', color: 'rgba(255,255,255,0.6)', marginBottom: '1.5rem' }}>
                                    Provide a Fine-Grained Personal Access Token (PAT) with repository access. This token is securely stored in your browser's local storage and used to proxy requests through our backend.
                                </p>

                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Personal Access Token (PAT)</label>
                                <input
                                    type="password"
                                    value={ghToken}
                                    onChange={(e) => setGhToken(e.target.value)}
                                    placeholder="ghp_********************************"
                                    style={{ width: '100%', padding: '0.75rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', marginBottom: '1rem' }}
                                />

                                <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '1rem' }}>
                                    {ghStatus === 'error' && <span style={{ color: 'var(--accent-red)', fontSize: '0.875rem' }}>Invalid token or insufficient scopes.</span>}
                                    {ghStatus === 'success' && <span style={{ color: 'var(--accent-green)', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}><CheckCircle size={16} /> Saved</span>}
                                    <button
                                        className="action-button primary"
                                        onClick={handleSaveGithub}
                                        disabled={ghStatus === 'testing' || !ghToken}
                                    >
                                        {ghStatus === 'testing' ? 'Validating...' : 'Save & Validate'}
                                    </button>
                                </div>
                            </div>
                        )}

                        {activeTab === 'llm' && (
                            <div className="animate-in">
                                <h3>LLM Configuration</h3>
                                <p style={{ fontSize: '0.875rem', color: 'rgba(255,255,255,0.6)', marginBottom: '1.5rem' }}>
                                    Configure the AI models used during the Analyze & Test phase. Keys are stored locally in your browser.
                                </p>

                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Provider</label>
                                <select
                                    value={llmProvider}
                                    onChange={(e) => {
                                        setLlmProvider(e.target.value);
                                    }}
                                    style={{ width: '100%', padding: '0.75rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', marginBottom: '1rem' }}
                                >
                                    <option value="Google">Google (Gemini)</option>
                                    <option value="OpenAI">OpenAI</option>
                                    <option value="Anthropic">Anthropic</option>
                                </select>

                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>API Key</label>
                                <input
                                    type="password"
                                    value={llmKey}
                                    onChange={(e) => setLlmKey(e.target.value)}
                                    placeholder={`Enter your ${llmProvider} API Key`}
                                    style={{ width: '100%', padding: '0.75rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', marginBottom: '1rem' }}
                                />

                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Default Boost Model</label>
                                <input
                                    type="text"
                                    value={llmModel}
                                    onChange={(e) => setLlmModel(e.target.value)}
                                    placeholder="e.g. gemini-1.5-pro"
                                    style={{ width: '100%', padding: '0.75rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', marginBottom: '1rem' }}
                                />

                                <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '1rem' }}>
                                    {llmStatus === 'success' && <span style={{ color: 'var(--accent-green)', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}><CheckCircle size={16} /> Saved to Local Storage</span>}
                                    <button
                                        className="action-button primary"
                                        onClick={handleSaveLLM}
                                        disabled={!llmKey}
                                    >
                                        Save Configuration
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

// Helper for the header icon
const SettingsIcon = () => <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>;

export default SettingsModal;
