import React, { useState, useEffect } from 'react';
import { Cpu, Play, Settings, LogOut, Box, AlertCircle, GitMerge, FlaskConical, Search } from 'lucide-react';
import { supabase } from './utils/supabaseClient';
import API_BASE from './config';
import StyleCapsuleManager from './components/StyleCapsuleManager';
import LoginPage from './pages/LoginPage';
import { useGithub } from './contexts/GithubProvider';
import RepoSelector from './components/RepoSelector';
import PRSelector from './components/PRSelector';
import SettingsModal from './components/SettingsModal';
import AnalysisTerminal from './components/AnalysisTerminal';
import RunHistory from './components/RunHistory';
import TestMappingMatrix from './components/TestMappingMatrix';
import SyncModal from './components/SyncModal';
import CommunityVisualizer from './components/CommunityVisualizer';
import InstrumentationModal from './components/InstrumentationModal';
import InstrumentationMapViewer from './components/InstrumentationMapViewer';
import FeatureManager from './components/FeatureManager';

function App() {
  const [session, setSession] = useState(null);
  const [isStyleManagerOpen, setIsStyleManagerOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAnalysisOpen, setIsAnalysisOpen] = useState(false);
  const [isMappingMatrixOpen, setIsMappingMatrixOpen] = useState(false);
  const [isCommunityVisualizerOpen, setIsCommunityVisualizerOpen] = useState(false);
  const [isInstrumentationOpen, setIsInstrumentationOpen] = useState(false);
  const [isInstrumentationMapOpen, setIsInstrumentationMapOpen] = useState(false);
  const [activeSync, setActiveSync] = useState(null); // { title, desc, endpoint, payload }
  const [isConfiguringAnalysis, setIsConfiguringAnalysis] = useState(false);
  const [currentRunId, setCurrentRunId] = useState(null);
  const [terminalMode, setTerminalMode] = useState('streaming');
  const [initialEvents, setInitialEvents] = useState([]);
  const [pastRuns, setPastRuns] = useState([]);
  const [duplicateRun, setDuplicateRun] = useState(null);
  
  const [selectedDevRepo, setSelectedDevRepo] = useState(null);
  const [selectedAutoRepo, setSelectedAutoRepo] = useState(null);
  const [selectedPR, setSelectedPR] = useState(null);
  const [llmModel, setLlmModel] = useState('');
  const [fetchedModels, setFetchedModels] = useState([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [projectFeatures, setProjectFeatures] = useState({});
  const [isFeatureManagerOpen, setIsFeatureManagerOpen] = useState(false);

  // Dynamic Project ID based on Repo (defaults to 1 for generic runs)
  const currentProjectId = selectedDevRepo?.id || 1;

  useEffect(() => {
    const isDemo = localStorage.getItem('demo_session') === 'true';
    
    if (isDemo) {
      setSession({
        user: {
          id: 'demo-user-id',
          email: 'demo@testsquad.io',
          user_metadata: {
            full_name: 'Demo User',
            avatar_url: 'https://api.dicebear.com/7.x/avataaars/svg?seed=demo'
          }
        },
        access_token: ''
      });
      return;
    }

    if (!supabase) return;

    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  const fetchModels = async () => {
    const provider = localStorage.getItem('llm_provider');
    const apiKey = localStorage.getItem('llm_api_key');
    
    if (!provider || !apiKey) return;
    
    if (!session) return;

    setIsLoadingModels(true);
    try {
      const res = await fetchWithGithub('${API_BASE}/api/llm/models');
      if (res.ok) {
        const models = await res.json();
        setFetchedModels(models);
        if (models.length > 0 && !llmModel) {
          setLlmModel(models[0].name);
        }
      }
    } catch (e) {
      console.error('Failed to fetch models:', e);
    } finally {
      setIsLoadingModels(false);
    }
  };

  useEffect(() => {
    if (session) {
      fetchModels();
    }
    window.addEventListener('llm-settings-updated', fetchModels);
    return () => window.removeEventListener('llm-settings-updated', fetchModels);
  }, [session]);

  const { fetchWithGithub } = useGithub();

  const handleRunOrchestrator = async (force = false) => {
    if (!selectedPR) {
      alert('Please select a Pull Request first.');
      return;
    }

    // Check for existing runs with same model and commit
    if (!force) {
      const currentCommit = selectedPR.head_sha || 'main';
      const existing = pastRuns.find(r => 
        r.run_metadata?.llm_model === llmModel && 
        r.commit_sha === currentCommit
      );
      if (existing) {
        setDuplicateRun(existing);
        return;
      }
    }

    setDuplicateRun(null);
    try {
      setTerminalMode('streaming');
      setInitialEvents([]);
      const res = await fetchWithGithub(`${API_BASE}/projects/${currentProjectId}/runs`, {
        method: 'POST',
        body: JSON.stringify({ 
          commit_sha: selectedPR.head_sha || 'main', 
          max_symbols: 3,
          llm_model: llmModel || (fetchedModels[0]?.name || 'gemini-1.5-flash-latest'),
          llm_provider: localStorage.getItem('llm_provider'),
          llm_api_key: localStorage.getItem('llm_api_key'),
          full_name: selectedDevRepo.full_name,
          pr_number: selectedPR.number,
          automation_repo: selectedAutoRepo ? selectedAutoRepo.full_name : null
        }),
        headers: { 
          'Content-Type': 'application/json',
          'X-LLM-Provider': localStorage.getItem('llm_provider'),
          'X-LLM-API-Key': localStorage.getItem('llm_api_key'),
          'X-LLM-Model': llmModel || (fetchedModels[0]?.name || 'gemini-1.5-flash-latest')
        }
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentRunId(data.run_id);
        setIsAnalysisOpen(true);
        // Refresh history after a short delay to ensure DB persistence
        setTimeout(fetchRunHistory, 2000);
      } else {
        alert('Failed to start orchestrator run.');
      }
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  const fetchRunHistory = async () => {
    if (!selectedPR) return;
    try {
      const res = await fetchWithGithub(`${API_BASE}/projects/${currentProjectId}/runs?commit_sha=${selectedPR.head_sha || 'main'}`);
      if (res.ok) {
        const data = await res.json();
        setPastRuns(data);
      }
    } catch (e) {
      console.error('Failed to fetch run history:', e);
    }
  };

  useEffect(() => {
    fetchRunHistory();
  }, [selectedPR]);

  useEffect(() => {
    if (!selectedDevRepo) return;
    fetchWithGithub(`${API_BASE}/projects/${currentProjectId}/features`)
      .then(r => r.json())
      .then(setProjectFeatures)
      .catch(() => setProjectFeatures({}));
  }, [selectedDevRepo, currentProjectId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('manage-features') === '1') {
      setIsFeatureManagerOpen(true);
    }
  }, []);

  const handleSelectRun = async (run) => {
    try {
      const res = await fetchWithGithub(`${API_BASE}/runs/${run.id}/events`);
      if (res.ok) {
        const data = await res.json();
        setInitialEvents(data.events || []);
        setCurrentRunId(run.id);
        setTerminalMode('replay');
        setIsAnalysisOpen(true);
      }
    } catch (e) {
      alert('Failed to load run history events.');
    }
  };

  const handleSyncRepo = async () => {
    try {
      const res = await fetchWithGithub(`${API_BASE}/projects/${currentProjectId}/sync`, {
        method: 'POST',
      });
      if (res.ok) {
        alert('Project brain sync started!');
      } else {
        alert('Failed to start sync.');
      }
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  };

  const handleLogout = async () => {
    if (localStorage.getItem('demo_session') === 'true') {
      localStorage.removeItem('demo_session');
      window.location.reload();
    } else {
      await supabase.auth.signOut();
    }
  };

  if (!session) {
    return <LoginPage />;
  }

  return (
    <div className="main-layout">
        {/* Background Orbs */}
        <div className="bg-orb orb-1" />
        <div className="bg-orb orb-2" />

        <main className="hero-content">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '3rem' }}>
            <div style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>
              <div>
                <h1 className="hero-title gradient-text" style={{ fontSize: '2.5rem', marginBottom: '0.25rem' }}>
                  TestRadius
                </h1>
                <p className="text-secondary" style={{ margin: 0, fontSize: '0.875rem' }}>
                  {session.user.user_metadata.full_name || session.user.email}
                </p>
              </div>
              
              <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
                <button 
                  onClick={() => setIsStyleManagerOpen(true)} 
                  className="action-button secondary"
                  style={{ background: 'rgba(56, 189, 248, 0.1)', color: 'var(--accent-blue)', padding: '0.5rem 1rem' }}
                >
                  <Box size={16} /> <span>Style</span>
                </button>
                <button 
                  onClick={() => setIsSettingsOpen(true)} 
                  className="action-button secondary"
                  style={{ background: 'rgba(255,255,255,0.05)', padding: '0.5rem 1rem' }}
                >
                  <Settings size={16} /> <span>Settings</span>
                </button>
                <button 
                  onClick={handleLogout} 
                  className="action-button" 
                  style={{ background: 'rgba(255,100,100,0.1)', color: '#ff8888', padding: '0.5rem 1rem' }}
                >
                  <LogOut size={16} /> <span>Logout</span>
                </button>
              </div>
            </div>
          </div>

          <div style={{ marginTop: '2rem' }}>
            <RepoSelector
              projectFeatures={projectFeatures}
              onOpenFeatureManager={() => setIsFeatureManagerOpen(true)}
              onSelectDevRepo={setSelectedDevRepo}
              onSelectAutoRepo={setSelectedAutoRepo}
              onOpenSettings={() => setIsSettingsOpen(true)}
              llmModel={llmModel}
              setLlmModel={setLlmModel}
              fetchedModels={fetchedModels}
              isLoadingModels={isLoadingModels}
              onSyncDevRepo={() => setActiveSync({
                title: "Production Brain Sync",
                desc: "Syncing codebase ASTs and symbol hierarchies into Neo4j Knowledge Graph.",
                endpoint: `${API_BASE}/projects/${currentProjectId}/sync`,
                payload: { 
                  repo_name: selectedDevRepo?.full_name,
                  model_name: llmModel
                }
              })}
              onSyncAutoRepo={() => setActiveSync({
                title: "Automation Brain Sync",
                desc: "Ingesting tracking repository ASTs to discover test signatures and paths.",
                endpoint: `${API_BASE}/projects/${currentProjectId}/sync-automation`,
                payload: { 
                  automation_repo: selectedAutoRepo?.full_name,
                  model_name: llmModel
                }
              })}
              onOpenMappingMatrix={() => {
                setIsMappingMatrixOpen(true);
              }}
              onOpenCommunities={() => {
                setIsCommunityVisualizerOpen(true);
              }}
              onOpenInstrumentation={() => {
                setIsInstrumentationOpen(true);
              }}
              onOpenInstrumentationMap={() => {
                setIsInstrumentationMapOpen(true);
              }}
            />

            <PRSelector
              selectedRepo={selectedDevRepo}
              onSelectPR={setSelectedPR}
            />

            {selectedPR && (
              <div className="animate-in" style={{ marginTop: '2rem' }}>
                <div className="glass" style={{ padding: '2rem', borderRadius: '1.5rem', background: 'rgba(255,255,255,0.03)' }}>
                  <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem' }}>{selectedPR.title}</h2>
                  <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>{selectedPR.body || 'No description provided.'}</p>
                  
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    {!isConfiguringAnalysis ? (
                      <React.Fragment>
                        <button className="action-button primary" onClick={() => setIsConfiguringAnalysis(true)}>
                          <Play size={18} /> Run Analysis
                        </button>
                        <button className="action-button secondary" onClick={() => setIsInstrumentationOpen(true)} style={{ background: 'rgba(56, 189, 248, 0.1)', color: 'var(--accent-blue)' }}>
                          <FlaskConical size={18} /> Instrument
                        </button>
                        <button className="action-button secondary" onClick={() => setIsInstrumentationMapOpen(true)} style={{ background: 'rgba(74, 222, 128, 0.1)', color: 'var(--accent-green)' }}>
                          <Search size={18} /> View Instr. Map
                        </button>
                      </React.Fragment>
                    ) : (
                      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', background: 'rgba(255,255,255,0.05)', padding: '0.5rem 1rem', borderRadius: '1rem', border: '1px solid rgba(255,255,255,0.1)' }}>
                        <span style={{ fontSize: '0.875rem', color: 'rgba(255,255,255,0.7)', fontWeight: 600 }}>Engine:</span>
                        <select 
                          className="glass" 
                          value={llmModel} 
                          onChange={(e) => setLlmModel(e.target.value)}
                          style={{ border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(0,0,0,0.5)', padding: '0.25rem 0.5rem', borderRadius: '0.5rem', color: 'white', outline: 'none', cursor: 'pointer' }}
                        >
                          <option value="">Repo-Native (Structural Only)</option>
                          {fetchedModels.map(model => <option key={model.name} value={model.name}>{model.name}</option>)}
                        </select>
                        <button className="action-button primary" onClick={() => {
                          setIsConfiguringAnalysis(false);
                          handleRunOrchestrator();
                        }} style={{ padding: '0.4rem 1.25rem', fontSize: '0.875rem' }}>
                          Start Analysis
                        </button>
                        <button style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)', cursor: 'pointer', fontSize: '0.875rem', paddingLeft: '0.5rem' }} onClick={() => setIsConfiguringAnalysis(false)}>
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>

                  {duplicateRun && (
                    <div className="animate-in" style={{ 
                      marginTop: '2rem', 
                      padding: '1.5rem', 
                      background: 'rgba(255, 165, 0, 0.03)', 
                      border: '1px solid rgba(255, 165, 0, 0.2)', 
                      borderRadius: '1.25rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '1rem'
                    }}>
                      <div style={{ display: 'flex', gap: '0.75rem', color: '#fbbf24' }}>
                        <AlertCircle size={20} style={{ flexShrink: 0, marginTop: '0.1rem' }} /> 
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: '0.25rem' }}>Previous Analysis Found</div>
                          <div style={{ fontSize: '0.875rem', opacity: 0.8, lineHeight: '1.5' }}>
                            A run with <strong>{llmModel}</strong> already exists for this commit (Run #{duplicateRun.id}). 
                            Would you like to view those results or execute a fresh analysis?
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', paddingLeft: '2.75rem' }}>
                        <button 
                          className="action-button primary" 
                          onClick={() => {
                            handleSelectRun(duplicateRun);
                            setDuplicateRun(null);
                          }}
                          style={{ 
                            fontSize: '0.8125rem', 
                            padding: '0.5rem 1.25rem',
                            background: '#fbbf24',
                            color: '#451a03'
                          }}
                        >
                          View Results
                        </button>
                        <button 
                          className="action-button secondary" 
                          onClick={() => handleRunOrchestrator(true)}
                          style={{ 
                            fontSize: '0.8125rem', 
                            padding: '0.5rem 1.25rem', 
                            background: 'rgba(255,255,255,0.05)',
                            color: 'white'
                          }}
                        >
                          Rerun Analysis
                        </button>
                        <button 
                          style={{ 
                            background: 'none', 
                            border: 'none', 
                            color: 'rgba(255,255,255,0.4)', 
                            fontSize: '0.8rem', 
                            cursor: 'pointer',
                            fontWeight: 600,
                            marginLeft: 'auto'
                          }}
                          onClick={() => setDuplicateRun(null)}
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Run History List */}
                  <RunHistory runs={pastRuns} onSelectRun={handleSelectRun} />
                </div>
              </div>
            )}
          </div>

        </main>


        <StyleCapsuleManager
          isOpen={isStyleManagerOpen}
          onClose={() => setIsStyleManagerOpen(false)}
          projectId={currentProjectId}
          automationRepoName={selectedAutoRepo?.full_name}
          availableModels={fetchedModels}
          selectedModel={llmModel}
          onModelChange={setLlmModel}
        />

        <SettingsModal
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          onOpenFeatureManager={() => setIsFeatureManagerOpen(true)}
        />

        {isAnalysisOpen && (
          <AnalysisTerminal 
            runId={currentRunId} 
            projectId={currentProjectId} 
            mode={terminalMode}
            initialEvents={initialEvents}
            onClose={() => setIsAnalysisOpen(false)} 
          />
        )}

        {projectFeatures?.test_mapping && isMappingMatrixOpen && (
          <TestMappingMatrix
            projectId={currentProjectId}
            autoRepoName={selectedAutoRepo?.full_name}
            autoRepoUrl={selectedAutoRepo?.html_url}
            llmModel={llmModel}
            setLlmModel={setLlmModel}
            fetchedModels={fetchedModels}
            isLoadingModels={isLoadingModels}
            onOpenInstrumentation={() => setIsInstrumentationOpen(true)}
            onClose={() => {
              setIsMappingMatrixOpen(false);
            }}
          />
        )}

        {projectFeatures?.communities && isCommunityVisualizerOpen && (
          <CommunityVisualizer
            projectId={currentProjectId}
            onClose={() => setIsCommunityVisualizerOpen(false)}
          />
        )}

        {activeSync && (
          <SyncModal
            title={activeSync.title}
            desc={activeSync.desc}
            endpoint={activeSync.endpoint}
            payload={activeSync.payload}
            onClose={() => setActiveSync(null)}
          />
        )}

        {projectFeatures?.instrumentation && isInstrumentationOpen && (
          <InstrumentationModal
            projectId={currentProjectId}
            repoUrl={selectedAutoRepo?.html_url}
            onClose={() => setIsInstrumentationOpen(false)}
          />
        )}

        {projectFeatures?.instrumentation_map && isInstrumentationMapOpen && (
          <InstrumentationMapViewer
            projectId={currentProjectId}
            onOpenInstrumentation={() => {
              setIsInstrumentationMapOpen(false);
              setTimeout(() => setIsInstrumentationOpen(true), 100);
            }}
            onClose={() => setIsInstrumentationMapOpen(false)}
          />
        )}

        {isFeatureManagerOpen && (
          <FeatureManager
            projectId={currentProjectId}
            isOpen={isFeatureManagerOpen}
            onClose={() => setIsFeatureManagerOpen(false)}
            onSaved={(features) => setProjectFeatures(features)}
            fetchWithGithub={fetchWithGithub}
          />
        )}
      </div>
  );
}

export default App;
