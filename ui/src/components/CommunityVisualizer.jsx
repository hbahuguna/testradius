import React, { useState, useEffect, useRef } from 'react';
import { X, Network, Maximize } from 'lucide-react';
import { useGithub } from '../contexts/GithubProvider';
import API_BASE from '../config';
import ForceGraph2D from 'react-force-graph-2d';
import * as d3 from 'd3';

export default function CommunityVisualizer({ projectId, onClose }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);
  const [recalcLogs, setRecalcLogs] = useState([]);
  const { fetchWithGithub } = useGithub();
  const fgRef = useRef();
  const containerRef = useRef();
  const [dimensions, setDimensions] = useState({ 
    width: 1350, 
    height: 850 
  });

  useEffect(() => {
    // Lock dimensions for stability
    setDimensions({
      width: Math.min(window.innerWidth - 80, 1350),
      height: Math.min(window.innerHeight - 100, 850)
    });
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const fetchGraphData = async (isRefresh = false) => {
    if (isRefresh) {
      setGraphData({ nodes: [], links: [] });
      setLoading(true);
    }
    
    let isMounted = true;
    const LIMIT = 500;
    
    const fetchBatch = async (offset = 0) => {
      try {
        const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/communities/graph?limit=${LIMIT}&offset=${offset}`);
        if (!res.ok) return;
        
        const data = await res.json();
        if (!isMounted) return;

        if (data.nodes.length > 0) {
          setGraphData(prev => ({
            nodes: [...prev.nodes, ...data.nodes.filter(n => !prev.nodes.find(pn => pn.id === n.id))],
            links: [...prev.links, ...data.links]
          }));
          
          if (data.nodes.length === LIMIT) {
            setTimeout(() => fetchBatch(offset + LIMIT), 1000);
          }
        }
      } catch (err) {
        console.error("Failed to fetch community graph batch", err);
      } finally {
        if (offset === 0) setLoading(false);
      }
    };

    fetchBatch(0);
    return () => { isMounted = false; };
  };

  useEffect(() => {
    fetchGraphData();
  }, [projectId]);

  const handleRecalculate = async () => {
    setRecalculating(true);
    setRecalcLogs([{ event: 'log', data: '🚀 Initializing Leiden engine...' }]);
    
    try {
      const res = await fetchWithGithub(`${API_BASE}/projects/${projectId}/communities/recalculate`, {
        method: 'POST'
      });
      
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const text = decoder.decode(value);
        const parts = text.split('\n\n');
        for (let part of parts) {
          if (part.startsWith('data: ')) {
            const payload = JSON.parse(part.replace('data: ', ''));
            if (payload.event === 'status' && payload.data.status === 'COMPLETED') {
              setRecalculating(false);
              fetchGraphData(true);
            } else {
              setRecalcLogs(prev => [...prev, payload]);
            }
          }
        }
      }
    } catch (err) {
      setRecalcLogs(prev => [...prev, { event: 'error', data: err.message }]);
      setRecalculating(false);
    }
  };

  useEffect(() => {
    if (!loading && fgRef.current) {
      // 1. Balanced Circular Repulsion
      const charge = fgRef.current.d3Force('charge');
      if (charge) charge.strength(-2500);
      
      // 2. Uniform Link distance
      const link = fgRef.current.d3Force('link');
      if (link) link.distance(150);

      // 3. RADIAL FORCE for the CIRCLE
      fgRef.current.d3Force('radial', d3.forceRadial(300, 0, 0));

      // 4. COLLISION prevention
      fgRef.current.d3Force('collision', d3.forceCollide(15));

      // 5. Absolute Center at 0,0
      const center = fgRef.current.d3Force('center');
      if (center) {
        center.x(0);
        center.y(0); 
      }
      
      // 6. Force the engine to re-heat and settle
      fgRef.current.d3ReheatSimulation();
    }
    
    // PROGRESSIVE ZOOM: Follow the expansion
    if (!loading && graphData.nodes.length > 0) {
      const t1 = setTimeout(() => {
        fgRef.current?.centerAt(0, 0, 400);
        fgRef.current?.zoomToFit(600, 40);
      }, 500);

      const t2 = setTimeout(() => {
        fgRef.current?.zoomToFit(800, 40);
      }, 2000);

      return () => {
        clearTimeout(t1);
        clearTimeout(t2);
      };
    }
  }, [loading, graphData.nodes.length, dimensions.width, dimensions.height]);

  const getColor = (communityId) => {
    const colors = [
      '#3b82f6', // blue
      '#a855f7', // purple
      '#10b981', // emerald
      '#f59e0b', // amber
      '#f43f5e', // rose
      '#6366f1', // indigo
      '#14b8a6', // teal
      '#84cc16'  // lime
    ];
    // Return a hex color
    return colors[(communityId || 0) % colors.length];
  };

  return (
    <div className="modal-overlay animate-in" style={{ backgroundColor: 'rgba(0,0,0,0.92)', zIndex: 1000 }} onClick={onClose}>
      <div 
        className="glass overflow-hidden relative" 
        style={{ 
          width: '95vw', 
          maxWidth: '1400px', 
          height: '90vh', 
          background: '#050505',
          borderRadius: '24px',
          border: '1px solid rgba(255,255,255,0.1)',
          boxShadow: '0 0 80px rgba(0, 0, 0, 0.8)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 1. OPTIMIZE (TOP RIGHT) */}
        <div className="absolute top-0 right-0 z-[110]">
          <button 
            onClick={handleRecalculate} 
            disabled={recalculating || loading}
            style={{
              background: recalculating ? 'rgba(245, 158, 11, 0.3)' : 'rgba(59, 130, 246, 0.15)',
              color: '#fff',
              padding: '0 28px',
              height: '60px',
              borderRadius: '0 24px 0 24px',
              fontSize: '13px',
              fontWeight: '800',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              borderLeft: '1px solid rgba(255,255,255,0.1)',
              borderBottom: '1px solid rgba(255,255,255,0.1)',
              backdropFilter: 'blur(24px)',
              transition: 'all 0.3s ease',
              cursor: (recalculating || loading) ? 'not-allowed' : 'pointer',
              letterSpacing: '0.05em'
            }}
          >
            <Network size={16} className={recalculating ? 'animate-spin' : ''} /> 
            {recalculating ? 'OPTIMIZING...' : 'OPTIMIZE CLUSTERS'}
          </button>
        </div>

        {/* 2. RESIZE VIEW (BOTTOM RIGHT) */}
        <div className="absolute bottom-0 right-0 z-[110]">
          <button 
            onClick={() => fgRef.current?.zoomToFit(600, 80)} 
            style={{
              background: 'rgba(255, 255, 255, 0.05)',
              color: '#fff',
              padding: '0 24px',
              height: '60px',
              borderRadius: '24px 0 24px 0',
              fontSize: '12px',
              fontWeight: '800',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              borderLeft: '1px solid rgba(255, 255, 255, 0.1)',
              borderTop: '1px solid rgba(255, 255, 255, 0.1)',
              backdropFilter: 'blur(24px)',
              transition: 'all 0.2s ease'
            }}
          >
            <Maximize size={16} /> RESIZE VIEW
          </button>
        </div>

        <div 
          className="absolute inset-0 bg-[#010101]" 
          ref={containerRef} 
          style={{ 
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.05)' 
          }}
        >
          {recalculating && (
            <div className="absolute bottom-6 right-6 z-[100] p-4 bg-black/60 backdrop-blur-xl border border-white/10 rounded-2xl max-w-[350px] overflow-y-auto font-mono text-[10px] text-blue-300 shadow-2xl">
              <div className="flex items-center gap-2 mb-2 text-white font-bold uppercase tracking-wider border-b border-white/10 pb-2">
                <Network size={12} className="animate-spin" /> Leiden Analysis
              </div>
              {recalcLogs.slice(-5).map((log, idx) => (
                <div key={idx} className="mb-1 opacity-80">
                  <span className="opacity-40">[{new Date().toLocaleTimeString()}]</span> {log.data}
                </div>
              ))}
              <div className="animate-pulse text-blue-400">Processing graph topology...</div>
            </div>
          )}
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-blue-400 animate-pulse flex items-center gap-2">
                <Network className="animate-spin" /> Rendering Physics Engine...
              </div>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-gray-400">
              No graph data available. Sync the production brain.
            </div>
          ) : (
            <ForceGraph2D
              ref={fgRef}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeColor={node => getColor(node.community_id)}
              nodeVal={node => Math.max(1, (node.val || 1) * 3)}
              nodeLabel={node => `${node.name}\nType: ${node.type}\nCommunity: ${node.community_id}`}
              nodeRelSize={6}
              linkColor={() => 'rgba(255,255,255,0.15)'}
              linkWidth={1.5}
              linkDirectionalParticles={2}
              linkDirectionalParticleSpeed={0.005}
              cooldownTicks={150}
              onEngineStop={() => {
                 // Final centering - Absolutely Centered
                 fgRef.current?.centerAt(0, 0, 400);
                 fgRef.current?.zoomToFit(600, 60);
               }}
              nodeCanvasObjectMode={() => 'after'}
              nodeCanvasObject={(node, ctx, globalScale) => {
                if (globalScale >= 2) {
                  const label = node.name;
                  const fontSize = 12 / globalScale;
                  ctx.font = `${fontSize}px Sans-Serif`;
                  ctx.textAlign = 'center';
                  ctx.textBaseline = 'middle';
                  ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
                  ctx.fillText(label, node.x, node.y + (node.val || 2) + 4);
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
