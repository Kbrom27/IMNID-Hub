import React, { useState, useEffect } from 'react';
import { AlertTriangle, Server, ShieldAlert, CheckCircle2, XCircle, HelpCircle, Lock } from 'lucide-react';
import Modal from './Modal';
import Button from './Button';
import Badge from './Badge';

const SYSTEM_NAMES = {
  openmrs: 'OpenMRS 3.x (Hospital EMR)',
  openmrs3: 'OpenMRS 3.x (Hospital EMR)',
  bahmni: 'Bahmni 0.93 (Legacy EMR)',
  dhis2: 'DHIS2 Tracker (Data Warehouse)',
  dhis2_online: 'DHIS2 Online (National Warehouse)',
  dhis2_offline: 'DHIS2 Offline (Facility Instance)',
  redcap: 'REDCap (Clinical Research)',
  mediator: 'Mediator Service (FastAPI)',
};

/**
 * ConfirmDialog Component
 * Standard write confirmation dialog with target system verification.
 * Enforces requirement:
 * - Must state target system name, effective URL, and source ('Saved in vault' / 'From environment').
 * - If target cannot be determined or is unconfigured, blocks the confirm button and warns the user.
 */
const ConfirmDialog = ({
  isOpen,
  open,
  onClose,
  onCancel,
  onConfirm,
  title = 'Confirm Action',
  description,
  message,
  targetServer,
  targetSystem,
  writeScope,
  actionLabel,
  confirmLabel,
  confirmText,
  cancelLabel = 'Cancel',
  variant = 'warning',
  loading = false,
}) => {
  const isVisible = isOpen ?? open ?? false;
  const handleClose = onClose || onCancel || (() => {});
  const displayTitle = title;
  const displayDescription = description || message;
  const primaryButtonLabel = actionLabel || confirmLabel || confirmText || 'Confirm & Run';

  const [connectionStatus, setConnectionStatus] = useState(null);
  const [fetchingStatus, setFetchingStatus] = useState(false);

  // Normalize target system key
  const normalizedKey = (targetSystem || targetServer || '').toLowerCase().trim();

  useEffect(() => {
    if (isVisible) {
      setFetchingStatus(true);
      fetch('/api/connections/status')
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data) setConnectionStatus(data);
        })
        .catch((e) => console.error('Failed to fetch connection status in ConfirmDialog:', e))
        .finally(() => setFetchingStatus(false));
    }
  }, [isVisible]);

  // Determine target info
  let targetInfo = null;
  if (connectionStatus && normalizedKey) {
    if (connectionStatus[normalizedKey]) {
      targetInfo = connectionStatus[normalizedKey];
    } else if (normalizedKey.includes('openmrs')) {
      targetInfo = connectionStatus['openmrs'];
    } else if (normalizedKey.includes('bahmni')) {
      targetInfo = connectionStatus['bahmni'];
    } else if (normalizedKey.includes('offline')) {
      targetInfo = connectionStatus['dhis2_offline'];
    } else if (normalizedKey.includes('online')) {
      targetInfo = connectionStatus['dhis2_online'];
    } else if (normalizedKey.includes('dhis2') || normalizedKey.includes('tracker')) {
      targetInfo = connectionStatus['dhis2_online'] || connectionStatus['dhis2'];
    } else if (normalizedKey.includes('redcap')) {
      targetInfo = connectionStatus['redcap'];
    } else if (normalizedKey.includes('mediator')) {
      targetInfo = connectionStatus['mediator'];
    }
  }

  // System configured check
  const isTargetDetermined = Boolean(
    targetInfo &&
    targetInfo.effective_url &&
    targetInfo.configured !== false &&
    !targetInfo.effective_url.includes('example.org')
  );

  const iconVariants = {
    danger: <ShieldAlert className="w-6 h-6 text-rose-600 dark:text-rose-400" />,
    warning: <AlertTriangle className="w-6 h-6 text-amber-600 dark:text-amber-400" />,
    primary: <Server className="w-6 h-6 text-teal-600 dark:text-teal-400" />,
  };

  const buttonVariants = {
    danger: 'danger',
    warning: 'primary',
    primary: 'primary',
  };

  return (
    <Modal
      isOpen={isVisible}
      onClose={loading ? () => {} : handleClose}
      size="md"
      title={
        <div className="flex items-center gap-2.5">
          {iconVariants[variant] || iconVariants.warning}
          <span className="text-base font-bold text-slate-900 dark:text-slate-100">{displayTitle}</span>
        </div>
      }
      footer={
        <div className="flex items-center justify-end gap-3 w-full">
          <Button variant="secondary" size="md" onClick={handleClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={buttonVariants[variant] || 'primary'}
            size="md"
            loading={loading}
            disabled={loading || !isTargetDetermined}
            onClick={onConfirm}
          >
            {primaryButtonLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-xs sm:text-sm text-slate-600 dark:text-slate-300">
        {displayDescription && <p className="leading-relaxed">{displayDescription}</p>}

        {/* Target Destination Server Verification Block */}
        <div className="p-3.5 bg-slate-50 dark:bg-slate-800/80 rounded-xl border border-slate-200 dark:border-slate-700/80 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Server className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
              Target Destination System
            </span>
            {targetInfo?.source && (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
                {targetInfo.source === 'vault' ? 'Saved in vault' : 'From environment'}
              </span>
            )}
          </div>

          {fetchingStatus ? (
            <div className="text-xs text-slate-400 flex items-center gap-2 py-1">
              <div className="w-3 h-3 border-2 border-teal-500 border-t-transparent rounded-full animate-spin"></div>
              <span>Resolving effective connection...</span>
            </div>
          ) : targetInfo ? (
            <div className="space-y-1 pt-0.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-800 dark:text-slate-100 text-xs sm:text-sm">
                  {targetInfo.name || SYSTEM_NAMES[normalizedKey] || normalizedKey}
                </span>
                {targetInfo.status === 'connected' ? (
                  <Badge variant="success" size="sm">Connected</Badge>
                ) : targetInfo.status === 'not_configured' ? (
                  <Badge variant="neutral" size="sm">Not Configured</Badge>
                ) : (
                  <Badge variant="warning" size="sm">Unreachable</Badge>
                )}
              </div>
              <div className="font-mono text-xs text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900 px-2.5 py-1.5 rounded border border-slate-200 dark:border-slate-800 truncate">
                {targetInfo.effective_url || 'No URL configured'}
              </div>
            </div>
          ) : (
            <div className="p-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 rounded border border-amber-200 dark:border-amber-800">
              Target selector: <code className="font-mono">{normalizedKey || 'Unspecified'}</code>
            </div>
          )}
        </div>

        {/* Blocking Warning if Target Cannot Be Determined */}
        {!fetchingStatus && !isTargetDetermined && (
          <div className="p-3 bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-800/80 rounded-xl text-rose-800 dark:text-rose-300 text-xs flex items-start gap-2.5">
            <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-bold block">Write Action Blocked</span>
              The destination system cannot be determined or is not configured. Real write operations require an active, configured target endpoint.
            </div>
          </div>
        )}

        {writeScope && (
          <div className="p-3 bg-amber-50/70 dark:bg-amber-950/30 rounded-xl border border-amber-200 dark:border-amber-800 space-y-1 text-amber-900 dark:text-amber-200">
            <span className="text-[11px] font-bold uppercase tracking-wider block">
              Data Modification Scope
            </span>
            <p className="text-xs leading-normal">{writeScope}</p>
          </div>
        )}
      </div>
    </Modal>
  );
};

export default ConfirmDialog;
