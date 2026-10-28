// Storage shared by the platform's Flex Consumption function apps: host state and one
// deployment container per app. Private (no public network access, no shared keys); the
// apps reach it through their integrated subnet and private endpoints.

param location string
param tags object = {}
param name string
@description('Deployment package containers, one per function app.')
param deploymentContainers string[]

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
    }
  }

  resource blobServices 'blobServices' = {
    name: 'default'

    resource containers 'containers' = [
      for container in deploymentContainers: {
        name: container
      }
    ]
  }
}

output id string = storage.id
output name string = storage.name
output blobEndpoint string = storage.properties.primaryEndpoints.blob
