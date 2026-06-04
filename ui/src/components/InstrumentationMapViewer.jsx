import React, { useState, useEffect, useCallback } from 'react';
import { X, FlaskConical, Search, RefreshCw, Cpu } from 'lucide-react';
import { useGithub } from '../contexts/GithubProvider';
import API_BASE from '../config';

const LIMIT = 50;

const InstrumentationMapViewer = ({ projectId, onClose, onOpenInstrumentation }) => {
  const { fetchWithGithub } = useGithub();
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [stats, setStats] = useState(null);

  const fetchMappings = useCallback(async (newOffset = 0, search = searchTerm) => {
    try {
      if (newOffset === 0) setLoading(true);
      const queryParam = search ? `&query=${encodeURIComponent(search)}` : '';
      const res = await fetchWithGithub(
        `${API_BASE}/projects/${projectId}/test-mapping?source=instrumentation&limit=${LIMIT}&offset=${newOffset}${queryParam}`
      );
      if (res.ok) {
        const data = await res.json();
        if (newOffset === 0) {
          setMappings(data);
        } else {
          setMappings(prev => [...prev, ...data]);
        }
        setHasMore(data.length === LIMIT);
        setOffset(newOffset);
      }
    } catch (e) {
      console.error('Failed to fetch instrumentation mappings', e);
    } finally {
      setLoading(false);
    }
  }, [projectId, searchTerm, fetchWithGithub]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetchWithGithub(
        `${API_BASE}/projects/${projectId}/test-mapping?source=instrumentation&limit=1`
      );
      if (res.ok) {
        const data = await res.json();
        if (data.length > 0) {
          const first = data[0];
          setStats({ count: '50+', source: first.status || 'TESTS' });
        } else {
          setStats(null);
        }
      }
    } catch (e) {
      // stats are best-effort
    }
  }, [projectId, fetchWithGithub]);

  useEffect(() => {
    fetchMappings(0, searchTerm);
  }, [searchTerm]);

  useEffect(() => {
    fetchMappings(0, '');
    fetchStats();
  }, [projectId]);

  const handleSearch = (e) => {
    setSearchTerm(e.target.value);
  };

  return (
    <div className="modal-overlay animate-in" style={{ backgroundColor: 'rgba(0,0,0,0.85)', zIndex: 1000 }}>
      <div className="glass" style={{ width: '90%', maxWidth: '1200px', height: '85vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <FlaskConical size={20} color="var(--accent-blue)" />
            <h3 style={{ margin: 0, color: 'var(--accent-blue)' }}>Instrumentation-Based Symbol-Test Map</h3>
            {stats && (
              <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', background: 'rgba(255,255,255,0.05)', padding: '0.25rem 0.75rem', borderRadius: '1rem' }}>
                source: {stats.source}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            {onOpenInstrumentation && (
              <button onClick={onOpenInstrumentation} className="action-button primary" style={{ fontSize: '0.875rem', padding: '0.5rem 1rem' }}>
                <Cpu size={16} /> Run Instrumentation
              </button>
            )}
            <button onClick={() => fetchMappings(0)} className="action-button secondary" style={{ fontSize: '0.875rem' }} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'spin' : ''} /> Refresh
            </button>
            <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', marginLeft: '0.5rem' }}>
              <X size={24} />
            </button>
          </div>
        </div>

        <div style={{ flex: 1, padding: '1.5rem', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          {loading && mappings.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'rgba(255,255,255,0.5)' }}>
              <FlaskConical size={32} style={{ marginBottom: '1rem', opacity: 0.5, display: 'inline-block' }} />
              <p>Loading instrumentation mappings...</p>
            </div>
          ) : mappings.length === 0 && !searchTerm ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'rgba(255,255,255,0.4)' }}>
              <FlaskConical size={32} style={{ marginBottom: '1rem', opacity: 0.5, display: 'inline-block' }} />
              <p>No instrumentation data found for this project.</p>
              <p style={{ fontSize: '0.875rem', marginTop: '0.5rem', color: 'rgba(255,255,255,0.3)' }}>
                Run instrumentation first to build test-to-symbol mappings via code coverage.
              </p>
              {onOpenInstrumentation && (
                <button onClick={onOpenInstrumentation} className="action-button primary" style={{ marginTop: '1rem', padding: '0.75rem 2rem' }}>
                  <Cpu size={16} /> Run Instrumentation
                </button>
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {mappings.length > 0 && (
                <div style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)', padding: '0.5rem 0' }}>
                  Showing {mappings.length} mappings{hasMore ? '+' : ''} &middot; All with confidence 1.0 from instrumentation
                </div>
              )}
              <div style={{ position: 'relative' }}>
                <Search size={18} style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.4)' }} />
                <input
                  type="text"
                  placeholder="Search by symbol or test name..."
                  value={searchTerm}
                  onChange={handleSearch}
                  style={{
                    width: '100%',
                    padding: '0.75rem 1rem 0.75rem 3rem',
                    borderRadius: '0.75rem',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: 'white',
                    outline: 'none'
                  }}
                />
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.5)', textAlign: 'left' }}>
                      <th style={{ padding: '1rem 0', minWidth: '180px' }}>Product Symbol</th>
                      <th style={{ minWidth: '200px' }}>Symbol File</th>
                      <th style={{ minWidth: '250px' }}>Test Symbol</th>
                      <th style={{ minWidth: '200px' }}>Test File</th>
                      <th style={{ width: '100px', textAlign: 'center' }}>Confidence</th>
                      <th style={{ width: '80px', textAlign: 'center' }}>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappings.map((m, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top' }}>
                          <div style={{ fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{m.product_symbol}</div>
                        </td>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top', fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>
                          {m.product_file}
                        </td>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top' }}>
                          <div style={{ color: '#a5d6ff' }}>{m.test_symbol}</div>
                        </td>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top', fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>
                          {m.test_file}
                        </td>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top', textAlign: 'center' }}>
                          <span style={{
                            padding: '0.2rem 0.5rem',
                            borderRadius: '1rem',
                            fontSize: '0.75rem',
                            background: 'rgba(0, 255, 128, 0.1)',
                            color: '#4caf50'
                          }}>
                            {m.confidence ? m.confidence.toFixed(2) : '1.00'}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem 0', verticalAlign: 'top', textAlign: 'center' }}>
                          <span style={{
                            padding: '0.2rem 0.5rem',
                            borderRadius: '1rem',
                            fontSize: '0.7rem',
                            background: 'rgba(56, 189, 248, 0.1)',
                            color: 'var(--accent-blue)'
                          }}>
                            {(m.status || 'TESTS').replace('_TEST', '')}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {hasMore && (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                    <button
                      onClick={() => fetchMappings(offset + LIMIT)}
                      className="action-button secondary"
                      style={{ padding: '0.75rem 2rem' }}
                      disabled={loading}
                    >
                      {loading ? 'Loading...' : 'Load More Mappings'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default InstrumentationMapViewer;
