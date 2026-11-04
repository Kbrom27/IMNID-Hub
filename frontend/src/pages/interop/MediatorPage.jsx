import React, { useState, useEffect } from 'react';
import { Activity, RotateCcw, AlertTriangle, RefreshCw, CheckCircle2, ExternalLink } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Badge,
  JobPanel,
  ConfirmDialog,
  MetricCard,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useInteropJob } from './useInteropJob';

/**
 * Interoperability Mediator & Checkpoint Page
 * Live health status, checkpoint inspection, failed record analytics, and resumption.
 */
const MediatorPage = () => {
  const { authHeader, isViewer } = useAuth();
  const {
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    cancelActiveJob,
    executeApiJob,
    resetJob,
  } = useInteropJob();

  const [mediatorStatus, setMediatorStatus] = useState(null);
  const [mediatorHealth, setMediatorHealth] = useState('checking');
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const fetchStatus = async () => {
    setLoadingStatus(true);
    try {
      const res = await fetch('/api/v1/interop/sync/status', { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setMediatorStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch status:', err);
    } finally {
      setLoadingStatus(false);
    }
  };

  const checkMediatorHealth = async () => {
    try {
      const res = await fetch('/api/v1/connections/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeader() },
        body: JSON.stringify({ system: 'mediator' }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok) {
          setMediatorHealth('healthy');
          return;
        }
      }
    } catch {
      // fallback
    }
    try {
      const res2 = await fetch('http://localhost:8000/health');
      if (res2.ok) {
        setMediatorHealth('healthy');
      } else {
        setMediatorHealth('unhealthy');
      }
    } catch {
      setMediatorHealth('offline');
    }
  };

  useEffect(() => {
    fetchStatus();
    checkMediatorHealth();
  }, []);

  const handleResumeSync = () => {
    setShowConfirm(false);
    executeApiJob('/api/v1/interop/sync/resume', {});
  };

  const checkpoint = mediatorStatus?.checkpoint;

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Mediator & Checkpoint Control"
        description="Inspect background mediator health and resume interrupted batch sync operations"
        breadcrumbs={[
          { label: 'Interoperability', href: '/interop' },
          { label: 'Mediator' },
        ]}
      />

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          title="Mediator Service Health"
          value={mediatorHealth.toUpperCase()}
          subtitle="Microservice Port 8000"
          badge={{
            text: mediatorHealth === 'healthy' ? 'Active' : 'Offline',
            variant: mediatorHealth === 'healthy' ? 'success' : 'danger',
          }}
          icon={<Activity className="w-5 h-5" />}
        />

        <MetricCard
          title="Last Checkpoint Facility"
          value={checkpoint?.facility_name || 'None'}
          subtitle={checkpoint?.system ? `System: ${checkpoint.system}` : 'No sync recorded'}
          badge={{
            text: checkpoint?.status || 'NO SYNC',
            variant: checkpoint?.status === 'completed' ? 'success' : 'warning',
          }}
        />

        <MetricCard
          title="Failed Records"
          value={mediatorStatus?.failed_records_count || 0}
          subtitle={`Extracted: ${checkpoint?.patients_extracted || 0} patients`}
          badge={{
            text: checkpoint?.can_resume ? 'Resumable' : 'Clean',
            variant: checkpoint?.can_resume ? 'warning' : 'neutral',
          }}
        />
      </div>

      {/* Actions & Resumption Card */}
      <Card>
        <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <CardTitle>Direct Checkpoint Resumption</CardTitle>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-750 transition-colors shadow-xs"
            >
              <ExternalLink className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
              Open API Docs (Swagger)
            </a>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className={`w-3.5 h-3.5 ${loadingStatus ? 'animate-spin' : ''}`} />}
              onClick={fetchStatus}
              disabled={loadingStatus}
            >
              Refresh Status
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<RotateCcw className="w-3.5 h-3.5" />}
              disabled={!checkpoint?.can_resume || isStreaming || isViewer}
              onClick={() => setShowConfirm(true)}
            >
              Resume Interrupted Sync
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4 border-t border-slate-100 dark:border-slate-800">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-3.5 bg-slate-50/80 dark:bg-slate-800/40 rounded-lg border border-slate-200/60 dark:border-slate-700/60 text-xs">
            <div>
              <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Sync Status</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200 capitalize">
                {checkpoint?.status?.replace(/_/g, ' ') || 'No Active Sync'}
              </span>
            </div>
            <div>
              <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Source System</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{checkpoint?.system || 'None'}</span>
            </div>
            <div>
              <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Visit Type / Program</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{checkpoint?.visit_type || checkpoint?.program || 'N/A'}</span>
            </div>
            <div>
              <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Last Updated</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {checkpoint?.updated_at ? new Date(checkpoint.updated_at).toLocaleTimeString() : 'N/A'}
              </span>
            </div>
          </div>

          {(checkpoint?.message || checkpoint?.error) && (
            <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-100/60 dark:bg-slate-800/60 p-2.5 rounded border border-slate-200/60 dark:border-slate-700/60">
              <span className="font-semibold text-slate-700 dark:text-slate-300">Checkpoint Details: </span>
              {checkpoint.message || checkpoint.error}
            </div>
          )}

          {mediatorStatus?.failed_records_detail?.length > 0 && (
            <div className="space-y-3 pt-2">
              <h4 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-500" />
                Failed Import Records Breakdown ({mediatorStatus.failed_records_detail.length} entries)
              </h4>

              <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-x-auto max-h-[360px]">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 uppercase text-[10px] tracking-wider sticky top-0">
                    <tr>
                      <th className="p-3">Record ID</th>
                      <th className="p-3">Patient</th>
                      <th className="p-3">Stage</th>
                      <th className="p-3">Field Name</th>
                      <th className="p-3">Value</th>
                      <th className="p-3">Reason</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {mediatorStatus.failed_records_detail.map((issue, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                        <td className="p-2.5 font-bold text-slate-800 dark:text-slate-200">{issue.record_id}</td>
                        <td className="p-2.5 text-slate-600 dark:text-slate-400">{issue.patient}</td>
                        <td className="p-2.5 text-slate-600 dark:text-slate-400">{issue.stage}</td>
                        <td className="p-2.5 text-slate-600 dark:text-slate-400">{issue.field_name}</td>
                        <td className="p-2.5 text-amber-700 dark:text-amber-400 bg-amber-50/40 dark:bg-amber-950/20">{issue.value}</td>
                        <td className="p-2.5 text-rose-600 dark:text-rose-400 font-sans">{issue.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={cancelActiveJob}
        onReset={resetJob}
        title="Resumption Job Progress"
      />

      <ConfirmDialog
        open={showConfirm}
        title="Resume Interrupted Sync?"
        message="Resuming sync will re-attempt importing failed and pending records from the last transformed checkpoint into DHIS2 Tracker."
        confirmText="Resume Sync"
        onConfirm={handleResumeSync}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default MediatorPage;
