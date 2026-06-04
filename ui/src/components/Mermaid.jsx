import React, { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

// Initialize mermaid with dark theme
mermaid.initialize({
  startOnLoad: true,
  theme: 'dark',
  securityLevel: 'loose',
  fontFamily: 'Inter, system-ui, sans-serif',
});

const Mermaid = ({ chart }) => {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current && chart) {
      try {
        // Clear previous content
        ref.current.innerHTML = chart;
        ref.current.removeAttribute('data-processed');
        mermaid.contentLoaded();
      } catch (err) {
        console.error('Mermaid render error:', err);
      }
    }
  }, [chart]);

  return (
    <div 
      className="mermaid" 
      ref={ref}
      style={{ 
        background: 'rgba(255,255,255,0.01)', 
        padding: '1.5rem', 
        borderRadius: '1rem',
        marginTop: '1rem',
        border: '1px solid rgba(255,255,255,0.05)',
        display: 'flex',
        justifyContent: 'center',
        overflowX: 'auto'
      }}
    >
      {chart}
    </div>
  );
};

export default Mermaid;
