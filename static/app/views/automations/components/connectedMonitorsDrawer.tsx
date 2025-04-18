import {useMemo} from 'react';
import styled from '@emotion/styled';

import {DrawerBody, DrawerHeader} from 'sentry/components/globalDrawer/components';
import SearchBar from 'sentry/components/searchBar';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import type {MonitorsData} from 'sentry/views/automations/components/connectedMonitorsList';
import ConnectedMonitorsList from 'sentry/views/automations/components/connectedMonitorsList';

export default function ConnectedMonitorsDrawer({monitors}: {monitors: MonitorsData[]}) {
  const connectedMonitors = useMemo(
    () => monitors.filter(monitor => monitor.connect.connected),
    [monitors]
  );
  const unconnectedMonitors = useMemo(
    () => monitors.filter(monitor => !monitor.connect.connected),
    [monitors]
  );

  return (
    <div>
      <DrawerHeader />
      <DrawerBody>
        <Heading>{t('Connected Monitors')}</Heading>
        <ConnectedMonitorsList monitors={connectedMonitors} />
        <Heading>{t('Other Monitors')}</Heading>
        <div style={{flexGrow: 1}}>
          <StyledSearchBar placeholder={t('Search for a monitor or project')} />
        </div>
        <ConnectedMonitorsList monitors={unconnectedMonitors} />
      </DrawerBody>
    </div>
  );
}

const Heading = styled('h2')`
  font-size: ${p => p.theme.fontSizeExtraLarge};
  margin-bottom: ${space(1.5)};
`;

const StyledSearchBar = styled(SearchBar)`
  flex-grow: 1;
  margin-bottom: ${space(2)};
`;
