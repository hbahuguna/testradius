import React from 'react';
import { Settings, Play, RefreshCw, Box, FlaskConical } from 'lucide-react';

const ActionBar = ({ onOpenStyleManager, onOpenSettings, onRunOrchestrator, onSyncRepo, onOpenInstrumentation }) => {
    return (
        <div className="action-bar-container">
            <div className="glass action-bar animate-in">
                <div className="action-bar-brand">
                    <Box size={20} style={{ marginRight: '0.5rem', color: 'var(--accent-blue)' }} />
                    <span className="brand-text">TestRadius</span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <ActionButton
                        icon={<RefreshCw size={18} />}
                        label="Sync"
                        onClick={onSyncRepo}
                    />
                    <ActionButton
                        icon={<Play size={18} />}
                        label="Run"
                        primary
                        onClick={onRunOrchestrator}
                    />
                    <ActionButton
                        icon={<FlaskConical size={18} />}
                        label="Instrument"
                        onClick={onOpenInstrumentation}
                    />
                    <ActionButton
                        icon={<Settings size={18} />}
                        label="Settings"
                        onClick={onOpenSettings}
                    />
                </div>
            </div>
        </div>
    );
};

const ActionButton = ({ icon, label, onClick, primary = false }) => {
    return (
        <button
            onClick={onClick}
            className={`action-button ${primary ? 'primary' : ''}`}
        >
            {icon}
            <span>{label}</span>
        </button>
    );
};

export default ActionBar;
