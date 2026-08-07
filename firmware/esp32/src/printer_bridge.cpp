#include "printer_bridge.h"

namespace plotter {

PrinterBridge::PrinterBridge(HardwareSerial& serial) : serial_(serial) {}

void PrinterBridge::begin() {
  inputBuffer_.reserve(config::kMaximumLineLength);
  serial_.begin(
      config::kPrinterBaud,
      SERIAL_8N1,
      config::kPrinterRxPin,
      config::kPrinterTxPin);
  appendLog("SYS", "UART1 ready on RX GPIO6 / TX GPIO7 at 115200 baud");
}

bool PrinterBridge::sendCommand(const String& command) {
  if (pending_ || command.isEmpty()) return false;
  serial_.print(command);
  serial_.print('\n');
  serial_.flush();
  lastCommand_ = command;
  pending_ = true;
  sentAtMs_ = millis();
  appendLog("TX", command);
  return true;
}

void PrinterBridge::emergencyStop() {
  serial_.print("M112\n");
  serial_.flush();
  pending_ = false;
  appendLog("TX", "M112");
  event_ = {BridgeEventType::Error, "Emergency stop sent; controller reset may be required."};
}

void PrinterBridge::poll() {
  while (serial_.available() > 0) {
    const char c = static_cast<char>(serial_.read());
    if (c == '\r') continue;
    if (c == '\n') {
      if (!inputBuffer_.isEmpty()) {
        processLine(inputBuffer_);
        inputBuffer_ = "";
      }
      continue;
    }
    if (inputBuffer_.length() < config::kMaximumLineLength) {
      inputBuffer_ += c;
    } else {
      inputBuffer_ = "";
      processLine("Error: printer response line exceeded safety limit");
    }
  }

  if (pending_ && static_cast<std::uint32_t>(millis() - sentAtMs_) > config::kPrinterTimeoutMs) {
    pending_ = false;
    event_ = {BridgeEventType::Timeout, "Timed out waiting for Marlin acknowledgement."};
    appendLog("ERR", event_.line);
  }
}

void PrinterBridge::processLine(String line) {
  line.trim();
  if (line.isEmpty()) return;

  connected_ = true;
  lastLine_ = line;
  ++receivedLines_;
  appendLog("RX", line);

  String lower = line;
  lower.toLowerCase();
  if (lower.startsWith("ok")) {
    pending_ = false;
    event_ = {BridgeEventType::Ok, line};
    return;
  }
  if (lower.startsWith("error") || lower.startsWith("!!")) {
    pending_ = false;
    event_ = {BridgeEventType::Error, line};
  }
}

BridgeEvent PrinterBridge::takeEvent() {
  BridgeEvent result = event_;
  event_ = {};
  return result;
}

void PrinterBridge::appendLog(const String& prefix, const String& line) {
  const std::size_t index = (logStart_ + logCount_) % log_.size();
  log_[index] = String(millis()) + " " + prefix + " " + line;
  if (logCount_ < log_.size()) {
    ++logCount_;
  } else {
    logStart_ = (logStart_ + 1) % log_.size();
  }
}

String PrinterBridge::jsonEscape(const String& value) {
  String escaped;
  escaped.reserve(value.length() + 8);
  for (std::size_t i = 0; i < value.length(); ++i) {
    const char c = value[i];
    switch (c) {
      case '\\': escaped += "\\\\"; break;
      case '"': escaped += "\\\""; break;
      case '\n': escaped += "\\n"; break;
      case '\r': escaped += "\\r"; break;
      case '\t': escaped += "\\t"; break;
      default:
        if (static_cast<unsigned char>(c) >= 0x20) escaped += c;
        break;
    }
  }
  return escaped;
}

String PrinterBridge::logJson() const {
  String json = "[";
  for (std::size_t i = 0; i < logCount_; ++i) {
    if (i > 0) json += ',';
    const std::size_t index = (logStart_ + i) % log_.size();
    json += '"';
    json += jsonEscape(log_[index]);
    json += '"';
  }
  json += ']';
  return json;
}

}  // namespace plotter
