import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import HmisIndex from './hmis/HmisIndex';
import HmisRmhReportPage from './hmis/HmisRmhReportPage';
import HmisNchReportPage from './hmis/HmisNchReportPage';
import NicuRegisterPage from './hmis/NicuRegisterPage';
import DeliveryRegisterPage from './hmis/DeliveryRegisterPage';
import MohAggregatePage from './hmis/MohAggregatePage';

const SUBPAGES = {
  'rmh-report': HmisRmhReportPage,
  'nch-report': HmisNchReportPage,
  'nicu-register': NicuRegisterPage,
  'delivery-register': DeliveryRegisterPage,
  'moh-aggregate': MohAggregatePage,

  // Backward compatibility aliases
  'rmh': HmisRmhReportPage,
  'nh': HmisNchReportPage,
  'nicu': NicuRegisterPage,
  'delivery': DeliveryRegisterPage,
};

/**
 * HmisPage Delegator
 * Directs to the corresponding HMIS reporting or register tool or renders the hub overview.
 */
const HmisPage = () => {
  const { feature } = useParams();
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab');

  const TargetPage = SUBPAGES[feature] || SUBPAGES[tab] || HmisIndex;
  return <TargetPage />;
};

export default HmisPage;
