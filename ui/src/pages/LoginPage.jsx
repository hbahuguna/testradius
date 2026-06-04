import React from 'react';
import { supabase } from '../utils/supabaseClient';
import { Github, Mail } from 'lucide-react';

const LoginPage = () => {
    const signInWithGithub = async () => {
        await supabase.auth.signInWithOAuth({
            provider: 'github',
            options: {
                scopes: 'repo read:user user:email'
            }
        });
    };

    const signInWithGoogle = async () => {
        await supabase.auth.signInWithOAuth({
            provider: 'google',
        });
    };

    return (
        <div className="main-layout">
            {/* Background Orbs */}
            <div className="bg-orb orb-1" />
            <div className="bg-orb orb-2" />

            <main className="hero-content glass" style={{ padding: '4rem', borderRadius: '2rem' }}>
                <h1 className="hero-title gradient-text" style={{ fontSize: '4rem', marginBottom: '1rem' }}>
                    TestRadius
                </h1>
                <p className="hero-subtitle">
                    Autonomous test engineering with deterministic intelligence.
                    Sign in to access your repository brain.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '2rem' }}>
                    <button
                        onClick={signInWithGithub}
                        className="action-button"
                        style={{
                            width: '100%',
                            justifyContent: 'center',
                            padding: '1.25rem',
                            background: 'white',
                            color: 'black',
                            fontSize: '1rem'
                        }}
                    >
                        <Github size={24} />
                        <span>Sign in with GitHub</span>
                    </button>

                    <button
                        onClick={signInWithGoogle}
                        className="action-button"
                        style={{
                            width: '100%',
                            justifyContent: 'center',
                            padding: '1.25rem',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            fontSize: '1rem'
                        }}
                    >
                        <Mail size={24} />
                        <span>Sign in with Google</span>
                    </button>

                    <div style={{ margin: '1rem 0', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.1)' }} />
                        <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em' }}>Demo Mode</span>
                        <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.1)' }} />
                    </div>

                    <button
                        onClick={() => {
                            localStorage.setItem('demo_session', 'true');
                            window.location.reload();
                        }}
                        className="action-button"
                        style={{
                            width: '100%',
                            justifyContent: 'center',
                            padding: '1rem',
                            background: 'rgba(56, 189, 248, 0.1)',
                            border: '1px solid rgba(56, 189, 248, 0.2)',
                            color: 'var(--accent-blue)',
                            fontSize: '0.9rem'
                        }}
                    >
                        <span>Enter Demo Mode (Bypass Auth)</span>
                    </button>
                </div>

                <p className="text-secondary" style={{ marginTop: '2rem', fontSize: '0.875rem', opacity: 0.6 }}>
                    By signing in, you agree to our Terms of Service.
                </p>
            </main>
        </div>
    );
};

export default LoginPage;
