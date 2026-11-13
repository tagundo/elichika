import Foundation
import Metal

let devices = MTLCopyAllDevices().map { device -> [String: Any] in
    ["name": device.name, "registry_id": String(device.registryID),
     "low_power": device.isLowPower, "removable": device.isRemovable,
     "unified_memory": device.hasUnifiedMemory,
     "max_buffer_length": device.maxBufferLength]
}
let defaultDevice = MTLCreateSystemDefaultDevice()
let record: [String: Any] = ["devices": devices, "has_default_device": defaultDevice != nil,
    "default_device_name": defaultDevice?.name ?? "",
    "qualification": "Read-only public Metal device enumeration. No GPU context or game state was replaced."]
let data = try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
