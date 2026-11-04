import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import DataManagementIndex from './data-management/DataManagementIndex';
import Dhis2SyncPage from './data-management/Dhis2SyncPage';
import CsvImportPage from './data-management/CsvImportPage';
import MetadataImportPage from './data-management/MetadataImportPage';
import CleaningPage from './data-management/CleaningPage';
import AnalysisExportPage from './data-management/AnalysisExportPage';
import DataExportPage from './data-management/DataExportPage';
import DataDictionaryPage from './data-management/DataDictionaryPage';
import RedcapImportPage from './data-management/RedcapImportPage';
import NcfNidSyncPage from './data-management/NcfNidSyncPage';
import MotherNeonateLinkerPage from './data-management/MotherNeonateLinkerPage';

const SUBPAGES = {
  'dhis2-sync': Dhis2SyncPage,
  dhis2_sync: Dhis2SyncPage,
  'csv-import': CsvImportPage,
  csv_import: CsvImportPage,
  'metadata-import': MetadataImportPage,
  metadata_import: MetadataImportPage,
  cleaning: CleaningPage,
  'analysis-export': AnalysisExportPage,
  analysis_export: AnalysisExportPage,
  'data-export': DataExportPage,
  data_export: DataExportPage,
  export: DataExportPage,
  'data-dictionary': DataDictionaryPage,
  data_dictionary: DataDictionaryPage,
  dictionary: DataDictionaryPage,
  'redcap-import': RedcapImportPage,
  redcap_import: RedcapImportPage,
  'ncf-nid-sync': NcfNidSyncPage,
  ncf_nid_sync: NcfNidSyncPage,
  'mother-neonate-linker': MotherNeonateLinkerPage,
  mother_neonate_linker: MotherNeonateLinkerPage,
};

/**
 * DataManagementPage Delegator
 * Directs to the requested feature sub-page or renders the hub overview.
 */
const DataManagementPage = () => {
  const { feature } = useParams();
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab');

  const TargetPage = SUBPAGES[feature] || SUBPAGES[tab] || DataManagementIndex;
  return <TargetPage />;
};

export default DataManagementPage;
