#pragma once

#include <cstddef>
#include <cstdint>

namespace plotter::config {

inline constexpr char kFirmwareName[] = "Printrbot Wi-Fi Bridge";
inline constexpr char kFirmwareVersion[] = "0.4.1-local";

inline constexpr int kPrinterUartIndex = 1;
inline constexpr int kPrinterRxPin = 6;
inline constexpr int kPrinterTxPin = 7;
inline constexpr std::uint32_t kPrinterBaud = 115200;
inline constexpr std::uint32_t kPrinterTimeoutMs = 15000;

inline constexpr int kRgbPin = 8;
inline constexpr int kRgbCount = 1;
inline constexpr std::uint8_t kRgbBrightness = 48;

inline constexpr char kAccessPointSsid[] = "Printrbot-Bridge";
inline constexpr char kAccessPointPassword[] = "plotter123";
inline constexpr char kMdnsHostname[] = "printrbot";

inline constexpr char kJobPath[] = "/active-job.gcode";
inline constexpr char kDraftPath[] = "/draft-job.gcode";
inline constexpr std::size_t kMaximumJobBytes = 512 * 1024;
inline constexpr std::size_t kMaximumCommands = 100000;

// These limits mirror the physically validated Rev F4 plotter configuration.
// The ESP32 uses them only to reject unsafe uploaded jobs; Marlin remains the
// real-time motion controller and enforces its own limits as well.
inline constexpr float kMachineXMinMm = 0.0F;
inline constexpr float kMachineXMaxMm = 152.4F;
inline constexpr float kMachineYMinMm = 0.0F;
inline constexpr float kMachineYMaxMm = 152.4F;
inline constexpr float kMachineZMinMm = 0.0F;
inline constexpr float kMachineZMaxMm = 152.4F;
inline constexpr float kMaximumXYFeedMmMin = 7500.0F;
inline constexpr float kMaximumZFeedMmMin = 300.0F;

inline constexpr float kSafeZUpMm = 5.0F;
inline constexpr std::uint32_t kSafeZFeedMmMin = 300;
// The bridge owns the pre-job homing guarantee. Uploaded jobs are still
// validated for their own safe end sequence, but cannot skip this step.
inline constexpr bool kForceHomeBeforeEveryJob = true;

inline constexpr std::size_t kLogLines = 24;
inline constexpr std::size_t kMaximumLineLength = 256;

}  // namespace plotter::config
