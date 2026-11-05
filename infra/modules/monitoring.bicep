// Log Analytics workspace and workspace-based Application Insights.

param location string
param tags object = {}
param logAnalyticsName string
param appInsightsName string
param privateNetworking bool = false

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    ...(privateNetworking ? {
      publicNetworkAccessForIngestion: 'Disabled'
      publicNetworkAccessForQuery: 'Disabled'
    } : {})
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    // Stays enabled: Foundry hosted-agent tracing ingests with the connection string.
    // The Functions app uses Entra ID ingestion (Monitoring Metrics Publisher) regardless.
    DisableLocalAuth: false
    ...(privateNetworking ? {
      publicNetworkAccessForIngestion: 'Disabled'
      publicNetworkAccessForQuery: 'Disabled'
    } : {})
  }
}

resource privateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = if (privateNetworking) {
  name: 'ampls-${appInsightsName}'
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource scopedLogs 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (privateNetworking) {
  parent: privateLinkScope
  name: 'workspace'
  properties: { linkedResourceId: logAnalytics.id }
}

resource scopedInsights 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (privateNetworking) {
  parent: privateLinkScope
  name: 'appinsights'
  properties: { linkedResourceId: appInsights.id }
}

output logAnalyticsId string = logAnalytics.id
output appInsightsId string = appInsights.id
output appInsightsName string = appInsights.name
output connectionString string = appInsights.properties.ConnectionString
output privateLinkScopeId string = privateNetworking ? privateLinkScope!.id : ''
