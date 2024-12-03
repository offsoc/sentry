import {defined} from 'sentry/utils';
import {generateFieldAsString} from 'sentry/utils/discover/fields';
import {getDatasetConfig} from 'sentry/views/dashboards/datasetConfig/base';
import {
  DisplayType,
  type Widget,
  type WidgetQuery,
  WidgetType,
} from 'sentry/views/dashboards/types';

import type {WidgetBuilderState} from '../hooks/useWidgetBuilderState';

export function convertBuilderStateToWidget(state: WidgetBuilderState): Widget {
  const datasetConfig = getDatasetConfig(state.dataset ?? WidgetType.ERRORS);
  const defaultQuery = datasetConfig.defaultWidgetQuery;

  const queries = defined(state.query) && state.query.length > 0 ? state.query : [''];

  const fields = state.fields?.map(generateFieldAsString);
  const aggregates = state.yAxis?.map(generateFieldAsString);
  const columns = state.fields
    ?.filter(field => 'kind' in field && field.kind === 'field')
    .map(generateFieldAsString);

  const widgetQueries: WidgetQuery[] = queries.map(query => {
    return {
      ...defaultQuery,
      fields: defined(fields) && fields.length > 0 ? fields : defaultQuery.fields,
      aggregates:
        defined(aggregates) && aggregates.length > 0
          ? aggregates
          : defaultQuery.aggregates,
      columns: defined(columns) && columns.length > 0 ? columns : defaultQuery.columns,
      conditions: query,
      // TODO: This will be read from the state under a separate key, not derived
      // from the fields. This is only to satisfy the type interface for now.
      orderby: defined(fields) && fields.length > 0 ? fields[0] : defaultQuery.orderby,
    };
  });

  return {
    title: state.title ?? '',
    description: state.description,
    displayType: state.displayType ?? DisplayType.TABLE,
    interval: '1h', // TODO: Not sure what to put here yet
    queries: widgetQueries,
    widgetType: state.dataset,
  };
}
