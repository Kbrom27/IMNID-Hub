import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  History,
  RotateCcw,
  Terminal,
  Download,
  X,
  StopCircle,
} from 'lucide-react';
import { PageHeader, StatusBadge } from '../ui';

const JobHistory = () => {
  const { authHeader, isViewer } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterModule, setFilterModule] = useState('');
  const [activeJob, setActiveJob] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [liveState, setLiveState] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const terminalEndRef = useRef(null);
  const eventSourceRef = useRef(null);

  const [appEnv, setAppEnv] = useState('production');

  const fetchJobs = async () => {
    try {
      const url = filterModule ? `/api/jobs?module=${filterModule}` : '/api/jobs';
      const res = await fetch(url, { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setJobs(data.jobs || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => {
        if (data.app_env) setAppEnv(data.app_env);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchJobs();
    const timer = setInterval(fetchJobs, 10000);
    return () => clearInterval(timer);
  }, [filterModule]);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [liveLogs]);

  const openLogViewer = (job) => {
    setActiveJob(job);
    setLiveLogs([]);
    setLiveState(job);
    startStream(job.id);
  };

  const closeLogViewer = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setActiveJob(null);
    setIsStreaming(false);
    fetchJobs();
  };

  const startStream = (jobId) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.type === 'log') {
          setLiveLogs((prev) => [...prev, parsed.data]);
        } else if (parsed.type === 'state') {
          setLiveState(parsed.data);
          if (['completed', 'failed', 'canceled'].includes(parsed.data.status)) {
            setIsStreaming(false);
          }
        }
      } catch (e) {
        console.error(e);
      }
    };

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
    };
  };

  const cancelJob = async (jobId) => {
    try {
      await fetch(`/api/jobs/${jobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      fetchJobs();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Job History & Audit Logs"
        description="Monitor background tasks, asynchronous pipelines, and execution traces"
        actions={
          <button
            onClick={fetchJobs}
            className="p-2.5 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-lg border border-slate-200 dark:border-slate-800 transition"
            title="Refresh list"
          >
            <RotateCcw className={`w-4 h-4 ${loading ? 'animate-spin text-teal-600' : ''}`} />
          </button>
        }
      />

      {/* Filter Row */}
      <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-wrap items-center gap-2">
        <span className="font-bold text-sm text-slate-700 dark:text-slate-300 mr-2">Filter Module:</span>
        {['', 'system', 'smartcare', 'data-management', 'interop', 'concepts', 'hmis'].map((mod) => (
          <button
            key={mod}
            onClick={() => setFilterModule(mod)}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition ${
              filterModule === mod
                ? 'bg-teal-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            {mod === '' ? 'All Modules' : mod}
          </button>
        ))}
      </div>

      {/* Jobs Table */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="bg-slate-50/80 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 font-bold uppercase text-xs tracking-wider">
              <th className="py-3.5 px-4">Job ID</th>
              <th className="py-3.5 px-4">Action / Pipeline</th>
              <th className="py-3.5 px-4">Module</th>
              <th className="py-3.5 px-4">Status</th>
              <th className="py-3.5 px-4">Progress</th>
              <th className="py-3.5 px-4">Created At</th>
              <th className="py-3.5 px-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800/80">
            {jobs.length === 0 ? (
              <tr>
                <td colSpan="7" className="py-12 text-center text-slate-400">
                  No jobs recorded yet.
                </td>
              </tr>
            ) : (
              jobs.map((j) => {
                const concreteAction =
                  j.action && j.action !== 'general' ? j.action : j.pipeline || `${j.module}_pipeline`;
                return (
                  <tr key={j.id} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition">
                    <td className="py-3 px-4 font-mono font-bold text-slate-700 dark:text-slate-300">{j.id}</td>
                    <td className="py-3 px-4 font-semibold text-slate-800 dark:text-slate-100">{concreteAction}</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-mono text-[11px]">
                        {j.module}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={j.status} />
                    </td>
                    <td className="py-3 px-4">
                      <div className="w-24">
                        <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full ${
                              j.status === 'completed' ? 'bg-emerald-500' : 'bg-teal-500'
                            }`}
                            style={{ width: `${j.progress || 0}%` }}
                          ></div>
                        </div>
                        <div className="text-[10px] text-slate-400 mt-0.5">{j.progress || 0}%</div>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                      {j.created_at?.slice(0, 19).replace('T', ' ')}
                    </td>
                    <td className="py-3 px-4 text-right space-x-1.5">
                      <button
                        onClick={() => openLogViewer(j)}
                        className="px-2.5 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/60 border border-teal-200 dark:border-teal-800 rounded transition"
                      >
                        View Logs
                      </button>
                      {j.status === 'running' && !isViewer && (
                        <button
                          onClick={() => cancelJob(j.id)}
                          className="px-2.5 py-1 text-xs font-semibold text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 border border-rose-200 dark:border-rose-800 rounded transition"
                        >
                          Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Streaming Log Modal */}
      {activeJob && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden text-slate-200">
            {/* Modal Header */}
            <div className="px-6 py-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Terminal className="w-5 h-5 text-teal-400" />
                <div>
                  <h3 className="font-bold text-sm text-white">
                    {liveState?.action || activeJob.action}
                  </h3>
                  <p className="text-xs text-slate-400 font-mono">Job ID: {activeJob.id} · Module: {activeJob.module}</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {liveState?.status === 'running' && !isViewer && (
                  <button
                    onClick={() => cancelJob(activeJob.id)}
                    className="flex items-center gap-1 px-3 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 rounded-lg text-xs font-semibold transition"
                  >
                    <StopCircle className="w-3.5 h-3.5" />
                    <span>Cancel</span>
                  </button>
                )}

                <a
                  href={`/api/jobs/${activeJob.id}/logs`}
                  download
                  className="flex items-center gap-1 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg text-xs font-medium transition"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download</span>
                </a>

                <button
                  onClick={closeLogViewer}
                  className="p-1 text-slate-400 hover:text-white rounded transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Progress Bar Header */}
            <div className="px-6 py-3 bg-slate-950/50 border-b border-slate-800/80 flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-400">Status:</span>
                <span className="font-bold uppercase text-teal-400">{liveState?.status || activeJob.status}</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-300">{liveState?.message || 'Processing...'}</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-36 h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-teal-400 transition-all duration-300"
                    style={{ width: `${liveState?.progress || 0}%` }}
                  ></div>
                </div>
                <span className="font-mono text-teal-400 font-bold">{liveState?.progress || 0}%</span>
              </div>
            </div>

            {/* Terminal Window */}
            <div className="flex-1 overflow-y-auto p-6 font-mono text-xs bg-slate-950 space-y-1 select-text">
              {liveLogs.length === 0 ? (
                <div className="text-slate-500 italic">Waiting for log stream events...</div>
              ) : (
                liveLogs.map((item, idx) => (
                  <div key={idx} className="flex items-start gap-2 leading-relaxed">
                    <span className="text-slate-600 select-none">[{item.timestamp}]</span>
                    <span
                      className={
                        item.level === 'ERROR'
                          ? 'text-rose-400 font-bold'
                          : item.level === 'WARN'
                          ? 'text-amber-400'
                          : 'text-teal-400'
                      }
                    >
                      [{item.level}]
                    </span>
                    <span className="text-slate-300 break-all">{item.text}</span>
                  </div>
                ))
              )}
              <div ref={terminalEndRef} />
            </div>

            {/* Footer */}
            <div className="px-6 py-2.5 bg-slate-950 border-t border-slate-800/80 text-[11px] text-slate-500 flex items-center justify-between">
              <span>Streaming via Server-Sent Events (SSE)</span>
              {isStreaming ? (
                <span className="flex items-center gap-1.5 text-teal-400">
                  <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse"></span>
                  Active Stream
                </span>
              ) : (
                <span className="text-slate-400">Stream Closed</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default JobHistory;
