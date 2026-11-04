import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';

/**
 * useVisitTypes Hook
 * Retrieves supported visit types from Bahmni or OpenMRS 3 server.
 */
export const useVisitTypes = (activeTab = 'bahmni') => {
  const { authHeader } = useAuth();
  const [visitTypes, setVisitTypes] = useState([
    { name: 'Delivery', uuid: 'delivery' },
    { name: 'NICU', uuid: 'nicu' },
    { name: 'ANC', uuid: 'anc' },
    { name: 'Labour and Delivery', uuid: 'labour' },
    { name: 'Facility Visit', uuid: 'facility' },
    { name: 'OPD Visit', uuid: 'opd' },
    { name: 'Offline Visit', uuid: 'offline' },
    { name: 'Home Visit', uuid: 'home' },
  ]);
  const [loadingVisitTypes, setLoadingVisitTypes] = useState(false);
  const [visitTypeMsg, setVisitTypeMsg] = useState(null);

  useEffect(() => {
    fetch(`/api/v1/interop/visit-types?system=${activeTab === 'o3' ? 'o3' : 'bahmni'}`, {
      headers: authHeader(),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && data.visit_types && data.visit_types.length > 0) {
          setVisitTypes(data.visit_types);
        }
      })
      .catch((err) => console.warn('Defaulted to schema visit types:', err));
  }, [activeTab, authHeader]);

  const handleLoadVisitTypes = useCallback(async (system) => {
    setLoadingVisitTypes(true);
    setVisitTypeMsg(null);
    try {
      const res = await fetch(`/api/v1/interop/visit-types?system=${system}`, {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        const types = data.visit_types || [];
        setVisitTypes(types);
        setVisitTypeMsg({
          type: 'success',
          text: `Loaded ${types.length} visit types live from ${system.toUpperCase()} server.`,
        });
      } else {
        const err = await res.json().catch(() => ({}));
        setVisitTypeMsg({ type: 'error', text: err.detail || 'Failed to load visit types' });
      }
    } catch (err) {
      setVisitTypeMsg({ type: 'error', text: String(err) });
    } finally {
      setLoadingVisitTypes(false);
    }
  }, [authHeader]);

  return {
    visitTypes,
    loadingVisitTypes,
    visitTypeMsg,
    handleLoadVisitTypes,
  };
};

export default useVisitTypes;
