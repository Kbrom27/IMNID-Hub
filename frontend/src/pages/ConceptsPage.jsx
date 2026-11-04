import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import ConceptsIndex from './concepts/ConceptsIndex';
import Openmrs3xToolsPage from './concepts/Openmrs3xToolsPage';
import Legacy21ToolsPage from './concepts/Legacy21ToolsPage';

const SUBPAGES = {
  '3x': Openmrs3xToolsPage,
  'openmrs-3x': Openmrs3xToolsPage,
  '3.x': Openmrs3xToolsPage,
  legacy21: Legacy21ToolsPage,
  'legacy-21': Legacy21ToolsPage,
  legacy: Legacy21ToolsPage,
};

/**
 * ConceptsPage Delegator
 * Directs to the requested schema or concept tool sub-page or renders the hub overview.
 */
const ConceptsPage = () => {
  const { feature } = useParams();
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab');

  const TargetPage = SUBPAGES[feature] || SUBPAGES[tab] || ConceptsIndex;
  return <TargetPage />;
};

export default ConceptsPage;
