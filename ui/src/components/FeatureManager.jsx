import React, { useState, useEffect } from 'react';
import { X, Plus, Check } from 'lucide-react';
import API_BASE from '../config';

const FEATURE_LABELS = {
  brain_sync: 'Brain Sync (Prod & Test)',
  test_mapping: 'Test Mapping',
  communities: 'Communities',
  instrumentation: 'Instrumentation',
  instrumentation_map: 'Instrumentation Map',
};

export default function FeatureManager({ projectId, isOpen, onClose, onSaved, fetchWithGithub }) {
  const [features, setFeatures] = useState({});
  const [newFlagName, setNewFlagName] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!isOpen || !projectId) return;
    fetchWithGithub(`${API_BASE}/projects/${projectId}/features`)
      .then(r => r.json())
      .then(setFeatures)
      .catch(() => setFeatures({}));
  }, [isOpen, projectId]);

  const toggle = (name) => {
    setFeatures(prev => ({ ...prev, [name]: !prev[name] }));
  };

  const addFlag = () => {
    const trimmed = newFlagName.trim();
    if (!trimmed || trimmed in features) return;
    setFeatures(prev => ({ ...prev, [trimmed]: true }));
    setNewFlagName('');
  };

  const save = async () => {
    setIsSaving(true);
    try {
      const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/features`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ features }),
      });
      if (res.ok) {
        onSaved?.(features);
        onClose();
      }
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content glass" onClick={e => e.stopPropagation()}
        style={{ maxWidth: '480px', padding: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h2 style={{ margin: 0 }}>Manage Features</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'white', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.5rem' }}>
          {Object.entries(features).map(([name, enabled]) => (
            <div key={name} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '0.75rem 1rem', borderRadius: '0.75rem',
              background: 'rgba(255,255,255,0.05)'
            }}>
              <span>{FEATURE_LABELS[name] || name}</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={enabled} onChange={() => toggle(name)} />
                <span className="toggle-slider" />
              </label>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
          <input
            value={newFlagName}
            onChange={e => setNewFlagName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addFlag()}
            placeholder="New flag name..."
            style={{
              flex: 1, padding: '0.5rem 0.75rem', borderRadius: '0.5rem',
              border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(0,0,0,0.3)', color: 'white', outline: 'none'
            }}
          />
          <button onClick={addFlag} className="action-button secondary"
            style={{ padding: '0.5rem 0.75rem' }}>
            <Plus size={16} />
          </button>
        </div>

        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
          <button onClick={onClose} className="action-button secondary">Cancel</button>
          <button onClick={save} className="action-button primary" disabled={isSaving}>
            <Check size={16} /> {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
