import React, { createContext, useContext, useState, useEffect } from 'react';
import { supabase } from '../utils/supabaseClient';
import API_BASE from '../config';

const GithubContext = createContext(null);

const getToken = () => localStorage.getItem('gh_provider_token');

export function GithubProvider({ children }) {
    const [providerToken, setProviderToken] = useState(() => getToken());
    const [serverFeatures, setServerFeatures] = useState({ vector_matching: false, llm: false });

    useEffect(() => {
        // Fetch server features on mount
        fetch(`${API_BASE}/features`)
            .then(res => res.json())
            .then(data => setServerFeatures(data))
            .catch(() => setServerFeatures({ vector_matching: false, llm: false }));
    }, []);

    useEffect(() => {
        const isDemo = localStorage.getItem('demo_session') === 'true';
        if (isDemo || !supabase) {
            const stored = getToken();
            if (stored) setProviderToken(stored);
            return;
        }

        supabase.auth.getSession().then(({ data: { session } }) => {
            if (session?.provider_token) {
                localStorage.setItem('gh_provider_token', session.provider_token);
                setProviderToken(session.provider_token);
            } else {
                const stored = getToken();
                if (stored) setProviderToken(stored);
            }
        });

        const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
            if (session?.provider_token) {
                localStorage.setItem('gh_provider_token', session.provider_token);
                setProviderToken(session.provider_token);
            } else if (!session) {
                localStorage.removeItem('gh_provider_token');
                setProviderToken(null);
            }
        });

        const handleTokenUpdate = () => {
            const stored = getToken();
            setProviderToken(stored || null);
        };
        window.addEventListener('gh-token-updated', handleTokenUpdate);

        return () => {
            subscription.unsubscribe();
            window.removeEventListener('gh-token-updated', handleTokenUpdate);
        };
    }, []);

    const fetchWithGithub = async (url, options = {}) => {
        let token = getToken();
        
        const isDemo = localStorage.getItem('demo_session') === 'true';
        
        // In demo mode, if no GH token is found, use a mock one if needed 
        // or just let it fail if the user didn't provide one.
        // For now, let's allow it to proceed.
        
        const llmProvider = localStorage.getItem('llm_provider');
        const llmKey = localStorage.getItem('llm_api_key');
        const llmModel = localStorage.getItem('llm_model');

        let accessToken = '';
        if (!isDemo) {
            const { data: { session } } = await supabase.auth.getSession();
            accessToken = session?.access_token ?? '';
        }
        
        // Build base headers with authorization
        const headers = {
            'X-GitHub-Token': token || '',
            'Authorization': `Bearer ${accessToken}`,
            ...options.headers,
        };

        // Only add LLM headers if not already provided (case-insensitive check)
        const existingKeys = Object.keys(headers).map(k => k.toLowerCase());
        
        if (!existingKeys.includes('x-llm-provider') && llmProvider) {
            headers['X-LLM-Provider'] = llmProvider;
        }
        if (!existingKeys.includes('x-llm-api-key') && llmKey) {
            headers['X-LLM-API-Key'] = llmKey;
        }
        if (!existingKeys.includes('x-llm-model') && llmModel) {
            headers['X-LLM-Model'] = llmModel;
        }

        return fetch(url, { ...options, headers });
    };

    return (
        <GithubContext.Provider value={{ providerToken, fetchWithGithub, serverFeatures }}>
            {children}
        </GithubContext.Provider>
    );
}

export const useGithub = () => useContext(GithubContext);
