import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  Server,
  Key,
  Save,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
  AlertCircle,
  ShieldAlert,
  Edit2,
  X
} from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent, Badge, Button } from '../ui';

const Settings = () => {
  const { authHeader, isOperator } = useAuth();
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testResults, setTestResults] = useState({});
  const [testing, setTesting] = useState({});
  const [saving, setSaving] = useState({});
  const [showPassword, setShowPassword] = useState({});
  const [changingSecret, setChangingSecret] = useState({});
  const [feedback, setFeedback] = useState({});

  const loadConnections = async () => {
    try {
      const res = await fetch('/api/settings/connections', { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setConnections(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConnections();
  }, []);

  const handleChange = (system, field, value) => {
    setConnections(prev =>
      prev.map(c => (c.system === system ? { ...c, [field]: value, ...(field === 'base_url' ? { configured_url: value } : {}) } : c))
    );
  };

  const testConnection = async (conn) => {
    setTesting(prev => ({ ...prev, [conn.system]: true }));
    setTestResults(prev => ({ ...prev, [conn.system]: null }));
    try {
      const res = await fetch('/api/connections/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader()
        },
        body: JSON.stringify({
          system: conn.system,
          base_url: conn.base_url || conn.configured_url || '',
          username: conn.username || '',
          secret: conn.new_secret || ''
        })
      });
      const data = await res.json();
      setTestResults(prev => ({ ...prev, [conn.system]: data }));
    } catch (e) {
      setTestResults(prev => ({
        ...prev,
        [conn.system]: { ok: false, error: e.message || 'Connection test failed' }
      }));
    } finally {
      setTesting(prev => ({ ...prev, [conn.system]: false }));
    }
  };

  const saveConnection = async (conn) => {
    setSaving(prev => ({ ...prev, [conn.system]: true }));
    setFeedback(prev => ({ ...prev, [conn.system]: null }));
    try {
      const payload = {
        name: conn.name,
        base_url: conn.base_url,
        username: conn.username || '',
        secret: conn.new_secret !== undefined ? conn.new_secret : undefined
      };
      const res = await fetch(`/api/settings/connections/${conn.system}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader()
        },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setFeedback(prev => ({ ...prev, [conn.system]: { success: true, message: 'Saved & Encrypted' } }));
        setChangingSecret(prev => ({ ...prev, [conn.system]: false }));
        await loadConnections();
      } else {
        const err = await res.json().catch(() => ({}));
        setFeedback(prev => ({ ...prev, [conn.system]: { success: false, message: err.detail || 'Save failed' } }));
      }
    } catch (e) {
      setFeedback(prev => ({ ...prev, [conn.system]: { success: false, message: e.message } }));
    } finally {
      setSaving(prev => ({ ...prev, [conn.system]: false }));
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Server Connections & Credentials Vault"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Administration', to: '/settings' },
        ]}
      />

      {!isOperator && (
        <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-sm flex items-center gap-2.5">
          <ShieldAlert className="w-5 h-5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
          <span>You are logged in as Viewer. You can test existing connections, but only Admins and Operators can modify credentials.</span>
        </div>
      )}

      {/* Two-column responsive card grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 lg:gap-6">
        {connections.map((c) => {
          const isTesting = testing[c.system];
          const isSaving = saving[c.system];
          const result = testResults[c.system];
          const feed = feedback[c.system];
          const isPasswordVisible = showPassword[c.system];
          const isEditingSecret = changingSecret[c.system] || !c.has_secret;
          const secretValue = c.new_secret !== undefined ? c.new_secret : '';

          return (
            <div
              key={c.system}
              className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-5 sm:p-6 flex flex-col justify-between space-y-4"
            >
              <div className="space-y-4">
                {/* Card Header */}
                <div className="flex items-start justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 border border-teal-200 dark:border-teal-800 flex items-center justify-center text-teal-700 dark:text-teal-300 flex-shrink-0">
                      <Server className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">{c.name}</h2>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[11px] text-slate-400 font-mono">system: {c.system}</span>
                        <span className="text-[10px] font-semibold px-2 py-0.2 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                          {c.source === 'vault' ? 'Saved in vault' : 'From environment'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <span className="text-[11px] font-mono text-slate-400">
                    {c.updated_at ? `Updated: ${c.updated_at.slice(0, 10)}` : ''}
                  </span>
                </div>

                {/* Input Fields (13px labels, 14px inputs) */}
                <div className="space-y-3.5">
                  <div>
                    <label htmlFor={`settings-${c.system}-url`} className="block text-[13px] font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Base Server URL
                    </label>
                    <input
                      id={`settings-${c.system}-url`}
                      type="text"
                      disabled={!isOperator}
                      value={c.base_url || ''}
                      onChange={(e) => handleChange(c.system, 'base_url', e.target.value)}
                      className="w-full px-3.5 py-2.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-100 font-mono text-[14px] focus:bg-white dark:focus:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-500"
                      placeholder={
                        c.system === 'dhis2_offline' ? 'http://localhost:8080/dhis' :
                        c.system === 'dhis2_online' ? 'https://imnid.aau.edu.et/dhis' :
                        c.system === 'dhis2_moh' ? 'https://dhis.moh.gov.et' :
                        c.system === 'openmrs' ? 'http://localhost/openmrs' :
                        c.system === 'bahmni' ? 'http://localhost:8080/openmrs' :
                        'https://server.example.org'
                      }
                    />
                    {/* Notice if env_url differs from vault */}
                    {c.env_url && (
                      <p className="mt-1 text-[11px] text-slate-500 italic">
                        Differs from .env value ({c.env_url}) (vault is used)
                      </p>
                    )}
                  </div>

                  {c.system !== 'mediator' && c.system !== 'redcap' && (
                    <div>
                      <label htmlFor={`settings-${c.system}-user`} className="block text-[13px] font-medium text-slate-700 dark:text-slate-300 mb-1">
                        Username / Account
                      </label>
                      <input
                        id={`settings-${c.system}-user`}
                        type="text"
                        disabled={!isOperator}
                        value={c.username || ''}
                        onChange={(e) => handleChange(c.system, 'username', e.target.value)}
                        className="w-full px-3.5 py-2.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-100 text-[14px] focus:bg-white dark:focus:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-500"
                        placeholder="admin"
                      />
                    </div>
                  )}

                  {c.system !== 'mediator' && (
                    <div>
                      <label htmlFor={`settings-${c.system}-secret`} className="block text-[13px] font-medium text-slate-700 dark:text-slate-300 mb-1">
                        {c.system === 'redcap' ? 'API Token (Encrypted)' : 'Password (Encrypted)'}
                      </label>

                      {c.has_secret && !changingSecret[c.system] ? (
                        <div className="flex items-center justify-between p-2.5 px-3.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 rounded-lg text-[14px]">
                          <span className="font-mono text-slate-600 dark:text-slate-400 select-none">
                            ••••••••••••
                          </span>
                          {isOperator && (
                            <button
                              type="button"
                              onClick={() => setChangingSecret(prev => ({ ...prev, [c.system]: true }))}
                              className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 flex items-center gap-1 cursor-pointer"
                            >
                              <Edit2 className="w-3 h-3" />
                              <span>{c.system === 'redcap' ? 'Change token' : 'Change password'}</span>
                            </button>
                          )}
                        </div>
                      ) : (
                        <div className="relative">
                          <input
                            id={`settings-${c.system}-secret`}
                            aria-label={c.system === 'redcap' ? 'API Token' : 'Password'}
                            type={isPasswordVisible ? 'text' : 'password'}
                            disabled={!isOperator}
                            value={secretValue}
                            onChange={(e) => handleChange(c.system, 'new_secret', e.target.value)}
                            placeholder={c.has_secret ? 'Enter new password to overwrite...' : 'Enter password...'}
                            className="w-full pl-3.5 pr-16 py-2.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-100 font-mono text-[14px] focus:bg-white dark:focus:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-500"
                          />
                          <div className="absolute inset-y-0 right-0 pr-2 flex items-center gap-1">
                            {/* Only show eye icon when secret is non-empty */}
                            {secretValue.length > 0 && (
                              <button
                                type="button"
                                onClick={() =>
                                  setShowPassword(prev => ({ ...prev, [c.system]: !prev[c.system] }))
                                }
                                className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                                title={isPasswordVisible ? 'Hide' : 'Show'}
                              >
                                {isPasswordVisible ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                              </button>
                            )}
                            {c.has_secret && (
                              <button
                                type="button"
                                onClick={() => {
                                  handleChange(c.system, 'new_secret', undefined);
                                  setChangingSecret(prev => ({ ...prev, [c.system]: false }));
                                }}
                                className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                                title="Cancel change"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Inline Test Result if available */}
                {result && (
                  <div
                    className={`p-3 rounded-lg text-xs flex items-start gap-2.5 ${
                      result.ok
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                        : 'bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-800'
                    }`}
                  >
                    {result.ok ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 flex-shrink-0 mt-0.5" />
                    ) : (
                      <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 flex-shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1">
                      <div className="font-semibold">
                        {result.ok ? `Connection Verified (${result.latency_ms} ms)` : 'Connection Test Failed'}
                      </div>
                      <div className="mt-0.5 text-[11px] opacity-90 truncate">
                        {result.ok
                          ? `Authenticated: ${JSON.stringify(result.details || {})}`
                          : result.error || 'Server unreachable'}
                      </div>
                    </div>
                  </div>
                )}

                {/* Save Feedback Toast */}
                {feed && (
                  <div
                    className={`p-2.5 rounded-lg text-xs font-medium ${
                      feed.success
                        ? 'bg-teal-50 dark:bg-teal-950/40 text-teal-800 dark:text-teal-300 border border-teal-200 dark:border-teal-800'
                        : 'bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-800'
                    }`}
                  >
                    {feed.message}
                  </div>
                )}
              </div>

              {/* Card Footer: Test & Save Buttons */}
              <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => testConnection(c)}
                  disabled={isTesting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/60 border border-teal-200 dark:border-teal-800 rounded-lg transition disabled:opacity-50 cursor-pointer"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isTesting ? 'animate-spin' : ''}`} />
                  <span>{isTesting ? 'Testing...' : 'Test Connection'}</span>
                </button>

                {isOperator && (
                  <button
                    type="button"
                    onClick={() => saveConnection(c)}
                    disabled={isSaving}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-lg shadow-sm transition disabled:opacity-50 cursor-pointer"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>{isSaving ? 'Saving...' : 'Save Vault'}</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Settings;
