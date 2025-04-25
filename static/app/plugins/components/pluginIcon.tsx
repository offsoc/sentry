import styled from '@emotion/styled';
import asana from 'sentry-logos/logo-asana.svg?raw';
import aws from 'sentry-logos/logo-aws.svg?raw';
import vsts from 'sentry-logos/logo-azure.svg?raw';
import bitbucket from 'sentry-logos/logo-bitbucket.svg?raw';
import bitbucketserver from 'sentry-logos/logo-bitbucket-server.svg?raw';
import placeholder from 'sentry-logos/logo-default.svg?raw';
import discord from 'sentry-logos/logo-discord.svg?raw';
import github from 'sentry-logos/logo-github.svg?raw';
import githubEnterprise from 'sentry-logos/logo-github-enterprise.svg?raw';
import gitlab from 'sentry-logos/logo-gitlab.svg?raw';
import heroku from 'sentry-logos/logo-heroku.svg?raw';
import jira from 'sentry-logos/logo-jira.svg?raw';
import jiraserver from 'sentry-logos/logo-jira-server.svg?raw';
import jumpcloud from 'sentry-logos/logo-jumpcloud.svg?raw';
import msteams from 'sentry-logos/logo-msteams.svg?raw';
import opsgenie from 'sentry-logos/logo-opsgenie.svg?raw';
import pagerduty from 'sentry-logos/logo-pagerduty.svg?raw';
import pivotal from 'sentry-logos/logo-pivotaltracker.svg?raw';
import pushover from 'sentry-logos/logo-pushover.svg?raw';
import redmine from 'sentry-logos/logo-redmine.svg?raw';
import segment from 'sentry-logos/logo-segment.svg?raw';
import sentry from 'sentry-logos/logo-sentry.svg?raw';
import slack from 'sentry-logos/logo-slack.svg?raw';
import trello from 'sentry-logos/logo-trello.svg?raw';
import twilio from 'sentry-logos/logo-twilio.svg?raw';
import vercel from 'sentry-logos/logo-vercel.svg?raw';
import victorops from 'sentry-logos/logo-victorops.svg?raw';
import visualstudio from 'sentry-logos/logo-visualstudio.svg?raw';

// Map of plugin id -> logo filename
const PLUGIN_ICONS = {
  placeholder,
  sentry,
  browsers: sentry,
  device: sentry,
  interface_types: sentry,
  os: sentry,
  urls: sentry,
  webhooks: sentry,
  'amazon-sqs': aws,
  aws_lambda: aws,
  asana,
  bitbucket,
  bitbucket_pipelines: bitbucket,
  bitbucket_server: bitbucketserver,
  discord,
  github,
  github_enterprise: githubEnterprise,
  gitlab,
  heroku,
  jira,
  jira_server: jiraserver,
  jumpcloud,
  msteams,
  opsgenie,
  pagerduty,
  pivotal,
  pushover,
  redmine,
  segment,
  slack,
  trello,
  twilio,
  visualstudio,
  vsts,
  vercel,
  victorops,
} satisfies Record<string, string>;

export interface PluginIconProps extends React.RefAttributes<HTMLDivElement> {
  pluginId: string | keyof typeof PLUGIN_ICONS;
  /**
   * @default 20
   */
  size?: number;
}

export function PluginIcon({pluginId, size = 20, ref}: PluginIconProps) {
  return (
    <StyledPluginIconContainer
      size={size}
      ref={ref}
      dangerouslySetInnerHTML={{__html: getPluginIconSource(pluginId)}}
    />
  );
}

const StyledPluginIconContainer = styled('div')<{
  size: number;
}>`
  height: ${p => p.size}px;
  width: ${p => p.size}px;
  min-width: ${p => p.size}px;
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
`;

function getPluginIconSource(
  pluginId: PluginIconProps['pluginId']
): (typeof PLUGIN_ICONS)[keyof typeof PLUGIN_ICONS] {
  if (!pluginId) {
    return PLUGIN_ICONS.placeholder;
  }

  if (pluginId in PLUGIN_ICONS) {
    return PLUGIN_ICONS[pluginId as keyof typeof PLUGIN_ICONS];
  }

  return PLUGIN_ICONS.placeholder;
}
