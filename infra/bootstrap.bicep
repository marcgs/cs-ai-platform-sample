// First private-environment phase, run from outside the VNet with explicit approval.
// The main template reuses exactly these resource names and module parameters.
targetScope = 'subscription'

param environmentName string
param location string
@minLength(1)
param adminPublicKey string
param vnetAddressPrefix string = '10.40.0.0/16'
param jumpVmSize string = 'Standard_B2s'
param privateEndpointSubnetNetworkSecurityGroupId string = ''
param functionsSubnetNetworkSecurityGroupId string = ''
param agentsSubnetNetworkSecurityGroupId string = ''

var abbrs = loadJsonContent('abbreviations.json')
var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location: location
    tags: tags
    vnetName: '${abbrs.networkVirtualNetworks}${token}'
    addressPrefix: vnetAddressPrefix
    privateNetworking: true
    privateEndpointSubnetNetworkSecurityGroupId: privateEndpointSubnetNetworkSecurityGroupId
    functionsSubnetNetworkSecurityGroupId: functionsSubnetNetworkSecurityGroupId
    agentsSubnetNetworkSecurityGroupId: agentsSubnetNetworkSecurityGroupId
  }
}

module jumpHost 'modules/jump-host.bicep' = {
  name: 'jump-host'
  scope: rg
  params: {
    location: location
    tags: tags
    name: 'vm-jump-${token}'
    subnetId: network.outputs.jumpSubnetId
    vnetId: network.outputs.vnetId
    vmSize: jumpVmSize
    adminPublicKey: adminPublicKey
  }
}

// The jump host runs azd up, which deploys at subscription scope and creates role assignments.
module jumpHostOwner 'modules/subscription-owner.bicep' = {
  name: 'jump-host-owner-${environmentName}'
  params: { principalId: jumpHost.outputs.principalId }
}

output resourceGroupName string = rg.name
output jumpVmName string = jumpHost.outputs.vmName
output bastionName string = jumpHost.outputs.bastionName
output jumpPrincipalId string = jumpHost.outputs.principalId
