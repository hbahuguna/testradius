import React, { useState, useEffect } from 'react';
import { useGithub } from '../contexts/GithubProvider';
import { GitBranch, FolderGit2, Settings, Brain, RefreshCw, GitMerge, Cpu, Network, FlaskConical, Search } from 'lucide-react';
import API_BASE from '../config';

const RepoSelector = ({ projectFeatures, onOpenFeatureManager, onSelectDevRepo, onSelectAutoRepo, onOpenSettings, llmModel, setLlmModel, fetchedModels, isLoadingModels, onSyncDevRepo, onSyncAutoRepo, onOpenMappingMatrix, onOpenCommunities, onOpenInstrumentation, onOpenInstrumentationMap }) => {
    const { fetchWithGithub } = useGithub();
    const [repos, setRepos] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);

    const [selectedDev, setSelectedDev] = useState('');
    const [selectedAuto, setSelectedAuto] = useState('');
    const [isSyncing, setIsSyncing] = useState(false);

    const loadRepos = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetchWithGithub('${API_BASE}/api/github/repositories');
            if (response.status === 401) {
                throw new Error("UNAUTHORIZED");
            }
            if (!response.ok) {
                throw new Error(`Failed to fetch repos: ${response.statusText}`);
            }
            const data = await response.json();
            setRepos(data);
        } catch (err) {
            console.error(err);
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };


    useEffect(() => {
        loadRepos();
        window.addEventListener('gh-token-updated', loadRepos);
        return () => window.removeEventListener('gh-token-updated', loadRepos);
    }, []);

    const handleDevChange = (e) => {
        const val = e.target.value;
        setSelectedDev(val);
        const repoObj = repos.find(r => r.full_name === val);
        if (onSelectDevRepo) onSelectDevRepo(repoObj);
    };

    const handleAutoChange = (e) => {
        const val = e.target.value;
        setSelectedAuto(val);
        const repoObj = repos.find(r => r.full_name === val);
        if (onSelectAutoRepo) onSelectAutoRepo(repoObj);
    };

    if (isLoading) return <div className="glass" style={{ padding: '1rem', borderRadius: '1rem' }}>Loading repositories...</div>;

    if (error === "UNAUTHORIZED") {
        return (
            <div className="glass" style={{ padding: '1.5rem', borderRadius: '1.5rem', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
                <p style={{ margin: 0, color: 'var(--accent-red)' }}>GitHub connection required to load repositories.</p>
                <button className="action-button primary" onClick={onOpenSettings}>
                    <Settings size={18} /> Configure GitHub Token
                </button>
            </div>
        );
    }

    if (error) return <div className="glass" style={{ padding: '1rem', borderRadius: '1rem', color: 'var(--accent-red)' }}>Error loading repos: {error}</div>;

    return (
        <div className="glass" style={{ padding: '1.5rem', borderRadius: '1.5rem', display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
            {/* Dev Repo Select */}
            <div style={{ flex: '1 1 300px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontSize: '0.875rem', color: 'rgba(255,255,255,0.7)' }}>
                    <FolderGit2 size={16} /> Dev Repository
                </label>
                <select
                    value={selectedDev}
                    onChange={handleDevChange}
                    style={{
                        width: '100%',
                        padding: '0.75rem',
                        borderRadius: '0.5rem',
                        background: 'rgba(0,0,0,0.2)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        outline: 'none'
                    }}
                >
                    <option value="">Select a repository...</option>
                    {repos.map(r => (
                        <option key={`dev-${r.id}`} value={r.full_name}>{r.full_name}</option>
                    ))}
                </select>
            </div>

            {/* Auto Repo Select */}
            <div style={{ flex: '1 1 300px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontSize: '0.875rem', color: 'rgba(255,255,255,0.7)' }}>
                    <GitBranch size={16} /> Automation Repository
                </label>
                <select
                    value={selectedAuto}
                    onChange={handleAutoChange}
                    style={{
                        width: '100%',
                        padding: '0.75rem',
                        borderRadius: '0.5rem',
                        background: 'rgba(0,0,0,0.2)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        outline: 'none'
                    }}
                >
                    <option value="">Select where tests are saved...</option>
                    {repos.map(r => (
                        <option key={`auto-${r.id}`} value={r.full_name}>{r.full_name}</option>
                    ))}
                </select>
            </div>

            {/* Intelligence Engine - Now Optional/Secondary */}
            <div style={{ flex: '1 1 200px', opacity: 0.6 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
                    <Cpu size={16} /> AI Boost (Optional)
                </label>
                <select
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                    disabled={isLoadingModels}
                    style={{
                        width: '100%',
                        padding: '0.75rem',
                        borderRadius: '0.5rem',
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        outline: 'none',
                        cursor: 'pointer'
                    }}
                >
                    <option value="">Repo-Native (Structural)</option>
                    {fetchedModels?.map(model => (
                        <option key={`model-${model.name}`} value={model.name}>{model.name}</option>
                    ))}
                </select>
            </div>

            {selectedDev && selectedAuto && selectedDev === selectedAuto && (
                <div style={{ 
                    flex: '1 1 100%', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    gap: '0.75rem',
                    padding: '0.75rem',
                    background: 'rgba(56, 189, 248, 0.1)',
                    border: '1px solid rgba(56, 189, 248, 0.2)',
                    borderRadius: '1rem',
                    color: 'var(--accent-blue)',
                    fontSize: '0.9rem',
                    fontWeight: 600
                }}>
                    <GitMerge size={18} />
                    Unified Repository Mode Active: Code and Tests will be indexed from the same source.
                </div>
            )}

            {/* Actions */}
            <div style={{ flex: '1 1 100%', display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '1.5rem', flexWrap: 'wrap' }}>
                {projectFeatures?.brain_sync && (<>
                <div className="tooltip">
                    <button 
                        onClick={() => onSyncDevRepo && onSyncDevRepo()} 
                        disabled={!selectedDev}
                        className={`action-button secondary ${!selectedDev ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem' }}
                    >
                        <Brain size={18} style={{ color: 'var(--accent-blue)' }} />
                        <span>Sync Prod Brain</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">Sync Production Code</span>
                        <span className="tooltip-desc">Indexes all functions and classes. Required for identifying high-risk changes.</span>
                    </div>
                </div>

                <div className="tooltip">
                    <button 
                        onClick={() => onSyncAutoRepo && onSyncAutoRepo()} 
                        disabled={!selectedAuto || !selectedDev}
                        className={`action-button secondary ${(!selectedAuto || !selectedDev) ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem' }}
                    >
                        <RefreshCw size={18} style={{ color: 'var(--accent-blue)' }} />
                        <span>Sync Test Brain</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">Sync Automation Code</span>
                        <span className="tooltip-desc">Ingest automation ASTs into the Knowledge Graph.</span>
                    </div>
                </div>
                </>)}

                {projectFeatures?.test_mapping && (
                <div className="tooltip">
                    <button 
                        onClick={() => onOpenMappingMatrix && onOpenMappingMatrix()} 
                        disabled={!selectedAuto || !selectedDev}
                        className={`action-button primary ${(!selectedAuto || !selectedDev) ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem' }}
                    >
                        <GitMerge size={18} />
                        <span>Test Map</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">View Code-to-Test Mapping</span>
                        <span className="tooltip-desc">View and manage existing relationships between code and tests.</span>
                    </div>
                </div>
                )}

                {projectFeatures?.communities && (
                <div className="tooltip">
                    <button 
                        onClick={() => onOpenCommunities && onOpenCommunities()} 
                        disabled={!selectedDev}
                        className={`action-button primary ${!selectedDev ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem', background: '#8b5cf6', color: 'white', borderColor: '#7c3aed' }}
                    >
                        <Network size={18} />
                        <span>View Communities</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">View Code Neighborhoods</span>
                        <span className="tooltip-desc">Visualize code grouped by AI-detected functional communities.</span>
                    </div>
                </div>
                )}

                {projectFeatures?.instrumentation && (
                <div className="tooltip">
                    <button 
                        onClick={() => onOpenInstrumentation && onOpenInstrumentation()} 
                        disabled={!selectedAuto || !selectedDev}
                        className={`action-button secondary ${(!selectedAuto || !selectedDev) ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem' }}
                    >
                        <FlaskConical size={18} style={{ color: 'var(--accent-blue)' }} />
                        <span>Instrument</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">Coverage Instrumentation</span>
                        <span className="tooltip-desc">Run tests with coverage to build a precise test-to-symbol map.</span>
                    </div>
                </div>
                )}

                {projectFeatures?.instrumentation_map && (
                <div className="tooltip">
                    <button
                        onClick={() => onOpenInstrumentationMap && onOpenInstrumentationMap()}
                        disabled={!selectedAuto || !selectedDev}
                        className={`action-button secondary ${(!selectedAuto || !selectedDev) ? 'disabled' : ''}`}
                        style={{ padding: '0.75rem 1.5rem', borderRadius: '1rem' }}
                    >
                        <Search size={18} style={{ color: 'var(--accent-green)' }} />
                        <span>View Instr. Map</span>
                    </button>
                    <div className="tooltip-text">
                        <span className="tooltip-title">View Instrumentation Map</span>
                        <span className="tooltip-desc">Browse existing test-to-symbol mappings from coverage instrumentation.</span>
                    </div>
                </div>
                )}
            </div>
        </div>
    );
};

export default RepoSelector;
