#pragma once

#include <Arduino.h>
#include <HardwareSerial.h>

#include <array>

#include "bridge_config.h"

namespace plotter {

enum class BridgeEventType {
  None,
  Ok,
  Error,
  Timeout,
};

struct BridgeEvent {
  BridgeEventType type{BridgeEventType::None};
  String line;
};

class PrinterBridge {
 public:
  explicit PrinterBridge(HardwareSerial& serial);

  void begin();
  void poll();
  bool sendCommand(const String& command);
  void emergencyStop();
  BridgeEvent takeEvent();

  bool pending() const { return pending_; }
  bool connected() const { return connected_; }
  const String& lastLine() const { return lastLine_; }
  const String& lastCommand() const { return lastCommand_; }
  std::uint32_t receivedLines() const { return receivedLines_; }
  String logJson() const;

 private:
  void processLine(String line);
  void appendLog(const String& prefix, const String& line);
  static String jsonEscape(const String& value);

  HardwareSerial& serial_;
  String inputBuffer_;
  String lastLine_;
  String lastCommand_;
  bool pending_{false};
  bool connected_{false};
  std::uint32_t sentAtMs_{0};
  std::uint32_t receivedLines_{0};
  BridgeEvent event_;
  std::array<String, config::kLogLines> log_{};
  std::size_t logStart_{0};
  std::size_t logCount_{0};
};

}  // namespace plotter
