"""Controlled SOAP property payloads, no live data."""
properties={
 ('vm-42','summary'):'<val xsi:type="VirtualMachineSummary"/>',
 ('ha-host','vm'):'<val xsi:type="ArrayOfManagedObjectReference"><ManagedObjectReference type="VirtualMachine">vm-42</ManagedObjectReference></val>',
 ('ha-host','hardware'):'<val xsi:type="HostHardwareInfo"><systemInfo><vendor>Dell Inc.</vendor><model>PowerEdge R650</model><uuid>12345678-1234-4321-8765-123456789abc</uuid></systemInfo><cpuInfo><numCpuPackages>1</numCpuPackages><numCpuCores>8</numCpuCores><numCpuThreads>16</numCpuThreads><hz>2400000000</hz></cpuInfo><memorySize>34359738368</memorySize></val>',
 ('ha-host','config'):'<val xsi:type="HostConfigInfo"/>',
 ('ha-host','datastore'):'<val xsi:type="ArrayOfManagedObjectReference"/>',
 ('vm-42','name'):'<val xsi:type="xsd:string" xmlns:xsd="http://www.w3.org/2001/XMLSchema">ESXI-VM</val>',
 ('vm-42','config'):'<val xsi:type="VirtualMachineConfigInfo"><name>ESXI-VM</name><uuid>42000000-1111-2222-3333-0123456789ab</uuid><instanceUuid>503c5ad7-0000-1111-2222-0123456789ab</instanceUuid><hardware><numCPU>4</numCPU><memoryMB>8192</memoryMB><device xsi:type="VirtualVmxnet3"><key>4000</key><deviceInfo><label>Network adapter 1</label><summary>VM Network</summary></deviceInfo><backing xsi:type="VirtualEthernetCardNetworkBackingInfo"><deviceName>VM Network</deviceName></backing><macAddress>00:50:56:aa:bb:01</macAddress><addressType>assigned</addressType></device></hardware></val>',
 ('vm-42','runtime'):'<val xsi:type="VirtualMachineRuntimeInfo"><powerState>poweredOn</powerState></val>',
 ('vm-42','guest'):'<val xsi:type="GuestInfo"><net><network>VM Network</network><ipAddress>10.20.40.42</ipAddress><macAddress>00:50:56:aa:bb:01</macAddress><connected>true</connected><deviceConfigId>4000</deviceConfigId><ipConfig><ipAddress><ipAddress>10.20.40.42</ipAddress><prefixLength>24</prefixLength></ipAddress></ipConfig></net></val>',
}
