// Virtual network for the data stores that may not be public.
//
// Storage (Functions host) and Cosmos DB (episodes) are reachable only through private
// endpoints. The function app and the hosted agents reach them from delegated subnets; the
// private DNS zones resolve their public host names to the private endpoint addresses.

param location string
param tags object = {}
param vnetName string
@description('Address space of the virtual network; the subnets are carved out of it.')
param addressPrefix string

// Azure DNS zone names for the private endpoint groups used in this sample.
var dnsZoneNames = {
  blob: 'privatelink.blob.${environment().suffixes.storage}'
  queue: 'privatelink.queue.${environment().suffixes.storage}'
  table: 'privatelink.table.${environment().suffixes.storage}'
  cosmosSql: 'privatelink.documents.azure.com'
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [addressPrefix]
    }
    subnets: [
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 24, 1)
        }
      }
      {
        // Flex Consumption integration; one app needs at least a /27.
        name: 'snet-functions'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 26, 8)
          delegations: [
            {
              name: 'functions'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
      {
        // Foundry agent network injection; dedicated to one Foundry account, /24 recommended.
        name: 'snet-agents'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 24, 3)
          delegations: [
            {
              name: 'agents'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
    ]
  }

  resource privateEndpointSubnet 'subnets' existing = {
    name: 'snet-private-endpoints'
  }

  resource functionsSubnet 'subnets' existing = {
    name: 'snet-functions'
  }

  resource agentsSubnet 'subnets' existing = {
    name: 'snet-agents'
  }
}

resource dnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [
  for zone in items(dnsZoneNames): {
    name: zone.value
    location: 'global'
    tags: tags
  }
]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [
  for (zone, i) in items(dnsZoneNames): {
    parent: dnsZones[i]
    name: vnet.name
    location: 'global'
    tags: tags
    properties: {
      registrationEnabled: false
      virtualNetwork: { id: vnet.id }
    }
  }
]

output vnetId string = vnet.id
output privateEndpointSubnetId string = vnet::privateEndpointSubnet.id
output functionsSubnetId string = vnet::functionsSubnet.id
output agentsSubnetId string = vnet::agentsSubnet.id
output dnsZoneIds object = {
  blob: resourceId('Microsoft.Network/privateDnsZones', dnsZoneNames.blob)
  queue: resourceId('Microsoft.Network/privateDnsZones', dnsZoneNames.queue)
  table: resourceId('Microsoft.Network/privateDnsZones', dnsZoneNames.table)
  cosmosSql: resourceId('Microsoft.Network/privateDnsZones', dnsZoneNames.cosmosSql)
}
