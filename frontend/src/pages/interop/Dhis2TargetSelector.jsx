import React from 'react';
import { Radio } from '../../ui';

/**
 * Dhis2TargetSelector Component
 * Allows selecting Online (Central) or Offline (Local) DHIS2 target using credentials from Connection Vault.
 */
export const Dhis2TargetSelector = ({ target, setTarget, vaultConns = {} }) => {
  const online = vaultConns.online;
  const offline = vaultConns.offline;

  return (
    <div className="p-4 bg-slate-50 dark:bg-slate-850 border border-slate-200 dark:border-slate-800 rounded-xl space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider">
          DHIS2 Destination Instance
        </label>
        <span className="text-[11px] text-slate-500">Using Vault Credentials</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div
          onClick={() => setTarget('online')}
          className={`p-3 rounded-xl border cursor-pointer transition flex items-start gap-3 ${
            target === 'online'
              ? 'bg-teal-50/80 dark:bg-teal-950/20 border-teal-500 ring-1 ring-teal-500'
              : 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-750'
          }`}
        >
          <Radio
            name="dhis2_dest"
            checked={target === 'online'}
            onChange={() => setTarget('online')}
          />
          <div>
            <span className="font-bold text-xs text-slate-900 dark:text-slate-100 block">
              Online DHIS2 (Central)
            </span>
            <span className="text-[11px] text-slate-500 font-mono block truncate max-w-[210px] mt-0.5">
              {online?.effective_url || online?.configured_url || online?.base_url || 'https://imnid.mohdigitalhealth.gov.et'}
            </span>
            <span className="inline-block mt-1.5 px-2 py-0.5 bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 rounded text-[10px] font-semibold">
              {online?.source === 'env' ? 'From Environment' : 'Saved in Vault'} ({online?.username || 'admin'})
            </span>
          </div>
        </div>

        <div
          onClick={() => setTarget('offline')}
          className={`p-3 rounded-xl border cursor-pointer transition flex items-start gap-3 ${
            target === 'offline'
              ? 'bg-teal-50/80 dark:bg-teal-950/20 border-teal-500 ring-1 ring-teal-500'
              : 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-750'
          }`}
        >
          <Radio
            name="dhis2_dest"
            checked={target === 'offline'}
            onChange={() => setTarget('offline')}
          />
          <div>
            <span className="font-bold text-xs text-slate-900 dark:text-slate-100 block">
              Offline DHIS2 (Local)
            </span>
            <span className="text-[11px] text-slate-500 font-mono block truncate max-w-[210px] mt-0.5">
              {offline?.effective_url || offline?.configured_url || offline?.base_url || 'http://localhost:8080'}
            </span>
            <span className="inline-block mt-1.5 px-2 py-0.5 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 rounded text-[10px] font-semibold">
              {offline?.source === 'env' ? 'From Environment' : 'Saved in Vault'} ({offline?.username || 'admin'})
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dhis2TargetSelector;
