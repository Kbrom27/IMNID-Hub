import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import InteropIndex from './interop/InteropIndex';
import BahmniPage from './interop/BahmniPage';
import Openmrs3Page from './interop/Openmrs3Page';
import ValueMappingsPage from './interop/ValueMappingsPage';
import MediatorPage from './interop/MediatorPage';

const SUBPAGES = {
  bahmni: BahmniPage,
  o3: Openmrs3Page,
  mappings: ValueMappingsPage,
  mediator: MediatorPage,
};

/**
 * InteropPage Delegator
 * Directs to the requested interoperability pipeline sub-page or renders the hub overview.
 */
const InteropPage = () => {
  const { feature } = useParams();
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab');

  const TargetPage = SUBPAGES[feature] || SUBPAGES[tab] || InteropIndex;
  return <TargetPage />;
};

export default InteropPage;
