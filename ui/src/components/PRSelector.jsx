import React, { useState, useEffect } from 'react';
import { useGithub } from '../contexts/GithubProvider';
import { GitPullRequest } from 'lucide-react';
import API_BASE from '../config';

const PRSelector = ({ selectedRepo, onSelectPR }) => {
    const { fetchWithGithub } = useGithub();
    const [prs, setPrs] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedPR, setSelectedPR] = useState('');

    useEffect(() => {
        const loadPRs = async () => {
            if (!selectedRepo) {
                setPrs([]);
                setSelectedPR('');
                return;
            }

            setIsLoading(true);
            setError(null);

            try {
                // selectedRepo is expected to be the full_name (e.g., owner/repo)
                const response = await fetchWithGithub(`${API_BASE}/api/github/repositories/${selectedRepo.full_name}/pulls`);
                if (!response.ok) {
                    throw new Error(`Failed to fetch PRs: ${response.statusText}`);
                }
                const data = await response.json();
                setPrs(data);
            } catch (err) {
                console.error(err);
                setError(err.message);
            } finally {
                setIsLoading(false);
            }
        };

        loadPRs();
    }, [selectedRepo]);

    const handleChange = (e) => {
        const val = e.target.value;
        setSelectedPR(val);
        // val is the PR ID as a string, find the actual object
        const prObj = prs.find(p => p.id.toString() === val);
        if (onSelectPR) onSelectPR(prObj);
    };

    if (!selectedRepo) {
        return (
            <div className="glass" style={{ padding: '1.5rem', borderRadius: '1.5rem', opacity: 0.5 }}>
                <p style={{ margin: 0 }}>Select a Dev Repository to view Pull Requests.</p>
            </div>
        );
    }

    if (isLoading) return <div className="glass" style={{ padding: '1.5rem', borderRadius: '1.5rem' }}>Loading Pull Requests for {selectedRepo.name}...</div>;
    if (error) return <div className="glass" style={{ padding: '1.5rem', borderRadius: '1.5rem', color: 'var(--accent-red)' }}>Error loading PRs: {error}</div>;

    return (
        <div className="glass animate-in" style={{ padding: '1.5rem', borderRadius: '1.5rem', marginTop: '1.5rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', fontSize: '1rem', fontWeight: 500 }}>
                <GitPullRequest size={20} style={{ color: 'var(--accent-blue)' }} />
                Active Pull Requests in {selectedRepo.name}
            </label>

            {prs.length === 0 ? (
                <p style={{ color: 'rgba(255,255,255,0.6)', margin: 0 }}>No open pull requests found.</p>
            ) : (
                <select
                    value={selectedPR}
                    onChange={handleChange}
                    style={{
                        width: '100%',
                        padding: '1rem',
                        borderRadius: '0.75rem',
                        background: 'rgba(0,0,0,0.3)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        outline: 'none',
                        fontSize: '1rem',
                        cursor: 'pointer'
                    }}
                >
                    <option value="">Select a Pull Request to Analyze...</option>
                    {prs.map(pr => (
                        <option key={pr.id} value={pr.id}>
                            #{pr.number} - {pr.title} ({pr.user})
                        </option>
                    ))}
                </select>
            )}
        </div>
    );
};

export default PRSelector;
