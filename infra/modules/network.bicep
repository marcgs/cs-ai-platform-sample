// Shared virtual network and private DNS, plus the jump host's subnet in private mode.
//
// Storage (Functions host) and Cosmos DB (episodes) are reachable only through private
// endpoints. The function app and the hosted agents reach them from delegated subnets; the
// private DNS zones resolve their public host names to the private endpoint addresses.

param location string
param tags object = {}
param vnetName string
@description('Address space of the virtual network; the subnets are carved out of it.')
param addressPrefix string

param privateEndpointSubnetNetworkSecurityGroupId string = ''
param functionsSubnetNetworkSecurityGroupId string = ''
param agentsSubnetNetworkSecurityGroupId string = ''
param privateNetworking bool = false

// Azure DNS zone names for the private endpoint groups used in this sample.
var dnsZoneNames = union({
  blob: 'privatelink.blob.${environment().suffixes.storage}'
  queue: 'privatelink.queue.${environment().suffixes.storage}'
  table: 'privatelink.table.${environment().suffixes.storage}'
  cosmosSql: 'privatelink.documents.azure.com'
}, privateNetworking ? {
  cognitive: 'privatelink.cognitiveservices.azure.com'
  openai: 'privatelink.openai.azure.com'
  foundry: 'privatelink.services.ai.azure.com'
  registry: 'privatelink.azurecr.io'
  search: 'privatelink.search.windows.net'
  web: 'privatelink.azurewebsites.net'
  monitor: 'privatelink.monitor.azure.com'
  oms: 'privatelink.oms.opinsights.azure.com'
  ods: 'privatelink.ods.opinsights.azure.com'
  agentService: 'privatelink.agentsvc.azure-automation.net'
} : {})

// No custom rules: the defaults allow SSH from inside the network and from Bastion Developer
// (Azure's platform address), and deny inbound from the internet. The VM has no public IP.
resource jumpNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = if (privateNetworking) {
  name: '${vnetName}-jump'
  location: location
  tags: tags
  properties: {
    securityRules: []
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [addressPrefix]
    }
    subnets: concat([
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 24, 1)
          ...(empty(privateEndpointSubnetNetworkSecurityGroupId) ? {} : {
            networkSecurityGroup: { id: privateEndpointSubnetNetworkSecurityGroupId }
          })
        }
      }
      {
        // Flex Consumption integration; one app needs at least a /27.
        name: 'snet-functions'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 26, 8)
          ...(empty(functionsSubnetNetworkSecurityGroupId) ? {} : {
            networkSecurityGroup: { id: functionsSubnetNetworkSecurityGroupId }
          })
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
          ...(empty(agentsSubnetNetworkSecurityGroupId) ? {} : {
            networkSecurityGroup: { id: agentsSubnetNetworkSecurityGroupId }
          })
          delegations: [
            {
              name: 'agents'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
    ], privateNetworking ? [
      {
        name: 'snet-jump'
        properties: {
          addressPrefix: cidrSubnet(addressPrefix, 24, 4)
          // Default outbound access, no NAT: governed subscriptions can block new public IPs.
          defaultOutboundAccess: true
          networkSecurityGroup: { id: jumpNsg!.id }
        }
      }
    ] : [])
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
output jumpSubnetId string = '${vnet.id}/subnets/snet-jump'
output dnsZoneIds object = toObject(
  items(dnsZoneNames),
  zone => zone.key,
  zone => resourceId('Microsoft.Network/privateDnsZones', zone.value)
)
