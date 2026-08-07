#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>

#include <string>

#include "bridge_config.h"
#include "job_runner.h"
#include "plotter_protocol.h"
#include "printer_bridge.h"
#include "web_page.h"

namespace {

HardwareSerial printerSerial(plotter::config::kPrinterUartIndex);
plotter::PrinterBridge printerBridge(printerSerial);
plotter::JobRunner jobRunner(printerBridge);
WebServer server(80);
DNSServer dnsServer;
Preferences preferences;
Adafruit_NeoPixel statusPixel(
    plotter::config::kRgbCount,
    plotter::config::kRgbPin,
    NEO_GRB + NEO_KHZ800);

File uploadFile;
bool uploadFailed = false;
String uploadError;
std::size_t uploadBytes = 0;
std::uint32_t lastLedUpdateMs = 0;

String jsonEscape(const String& value) {
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

void sendJson(int status, const String& body) {
  server.sendHeader("Cache-Control", "no-store");
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(status, "application/json", body);
}

void sendOk(const String& message = "ok") {
  sendJson(200, "{\"ok\":true,\"message\":\"" + jsonEscape(message) + "\"}");
}

void sendError(int status, const String& message) {
  sendJson(status, "{\"ok\":false,\"error\":\"" + jsonEscape(message) + "\"}");
}

String activeIp() {
  if (WiFi.status() == WL_CONNECTED) return WiFi.localIP().toString();
  return WiFi.softAPIP().toString();
}

String wifiModeName() {
  if (WiFi.status() == WL_CONNECTED) {
    return "AP + station (" + WiFi.SSID() + ")";
  }
  return "setup access point";
}

void setPixel(std::uint8_t red, std::uint8_t green, std::uint8_t blue) {
  statusPixel.setBrightness(plotter::config::kRgbBrightness);
  statusPixel.setPixelColor(0, statusPixel.Color(red, green, blue));
  statusPixel.show();
}

void updateStatusPixel() {
  if (millis() - lastLedUpdateMs < 120) return;
  lastLedUpdateMs = millis();

  switch (jobRunner.state()) {
    case plotter::JobState::Running:
      setPixel(0, 180, 55);
      break;
    case plotter::JobState::Paused:
    case plotter::JobState::Cancelling:
      setPixel(220, 95, 0);
      break;
    case plotter::JobState::Failed:
    case plotter::JobState::Emergency:
      setPixel(220, 0, 20);
      break;
    case plotter::JobState::Ready:
      setPixel(0, 95, 220);
      break;
    case plotter::JobState::Completed:
      setPixel(0, 180, 160);
      break;
    default:
      setPixel(printerBridge.connected() ? 45 : 95, 0, 125);
      break;
  }
}

void configureWifi() {
  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP_STA);

  const IPAddress apIp(192, 168, 4, 1);
  const IPAddress gateway(192, 168, 4, 1);
  const IPAddress subnet(255, 255, 255, 0);
  WiFi.softAPConfig(apIp, gateway, subnet);
  WiFi.softAP(
      plotter::config::kAccessPointSsid,
      plotter::config::kAccessPointPassword,
      6,
      false,
      4);

  const String ssid = preferences.getString("ssid", "");
  const String password = preferences.getString("password", "");
  if (!ssid.isEmpty()) {
    WiFi.setAutoReconnect(true);
    WiFi.begin(ssid.c_str(), password.c_str());
  }

  dnsServer.start(53, "*", apIp);
  MDNS.begin(plotter::config::kMdnsHostname);
  MDNS.addService("http", "tcp", 80);
}

void handleStatus() {
  String json;
  json.reserve(1200);
  json += "{";
  json += "\"firmware\":\"";
  json += plotter::config::kFirmwareName;
  json += " ";
  json += plotter::config::kFirmwareVersion;
  json += "\",";
  json += "\"uptime_ms\":" + String(millis()) + ",";
  json += "\"wifi_mode\":\"" + jsonEscape(wifiModeName()) + "\",";
  json += "\"ip\":\"" + jsonEscape(activeIp()) + "\",";
  json += "\"ap_ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"printer_connected\":" + String(printerBridge.connected() ? "true" : "false") + ",";
  json += "\"printer_pending\":" + String(printerBridge.pending() ? "true" : "false") + ",";
  json += "\"last_printer_line\":\"" + jsonEscape(printerBridge.lastLine()) + "\",";
  json += "\"job\":{";
  json += "\"state\":\"" + String(jobRunner.stateName()) + "\",";
  json += "\"total\":" + String(jobRunner.totalCommands()) + ",";
  json += "\"completed\":" + String(jobRunner.completedCommands()) + ",";
  json += "\"bytes\":" + String(jobRunner.jobBytes()) + ",";
  json += "\"progress\":" + String(jobRunner.progressPercent(), 2) + ",";
  json += "\"active\":\"" + jsonEscape(jobRunner.activeCommand()) + "\",";
  json += "\"error\":\"" + jsonEscape(jobRunner.lastError()) + "\"";
  json += "},";
  json += "\"log\":" + printerBridge.logJson();
  json += "}";
  sendJson(200, json);
}

void handleUploadChunk() {
  HTTPUpload& upload = server.upload();

  if (upload.status == UPLOAD_FILE_START) {
    uploadFailed = false;
    uploadError = "";
    uploadBytes = 0;

    if (jobRunner.busy()) {
      uploadFailed = true;
      uploadError = "Cannot replace a job while hardware motion is active.";
      return;
    }

    if (uploadFile) uploadFile.close();
    LittleFS.remove(plotter::config::kJobPath);
    uploadFile = LittleFS.open(plotter::config::kJobPath, FILE_WRITE);
    if (!uploadFile) {
      uploadFailed = true;
      uploadError = "LittleFS could not create the uploaded job.";
    }
    return;
  }

  if (upload.status == UPLOAD_FILE_WRITE) {
    if (uploadFailed) return;
    if (uploadBytes + upload.currentSize > plotter::config::kMaximumJobBytes) {
      uploadFailed = true;
      uploadError = "Job exceeds the 512 KiB upload limit.";
      if (uploadFile) uploadFile.close();
      LittleFS.remove(plotter::config::kJobPath);
      return;
    }
    if (!uploadFile || uploadFile.write(upload.buf, upload.currentSize) != upload.currentSize) {
      uploadFailed = true;
      uploadError = "Failed while writing the uploaded job to flash.";
      if (uploadFile) uploadFile.close();
      LittleFS.remove(plotter::config::kJobPath);
      return;
    }
    uploadBytes += upload.currentSize;
    return;
  }

  if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) uploadFile.close();
    if (uploadFailed) return;
    String error;
    if (!jobRunner.loadStoredJob(LittleFS, plotter::config::kJobPath, error)) {
      uploadFailed = true;
      uploadError = error;
      LittleFS.remove(plotter::config::kJobPath);
    }
    return;
  }

  if (upload.status == UPLOAD_FILE_ABORTED) {
    uploadFailed = true;
    uploadError = "Upload was aborted.";
    if (uploadFile) uploadFile.close();
    LittleFS.remove(plotter::config::kJobPath);
  }
}

void finishUploadRequest() {
  if (uploadFile) uploadFile.close();
  if (uploadFailed) {
    sendError(400, uploadError);
    return;
  }
  sendOk("Job validated and stored.");
}

void handleJobAction(const char* action) {
  String error;
  bool ok = false;
  const String requested(action);

  if (requested == "start") {
    if (printerBridge.pending()) {
      sendError(409, "Wait for the active printer query to finish.");
      return;
    }
    ok = jobRunner.start(LittleFS, error);
  } else if (requested == "pause") {
    ok = jobRunner.pause(error);
  } else if (requested == "resume") {
    ok = jobRunner.resume(error);
  } else if (requested == "cancel") {
    ok = jobRunner.cancel(error);
  }

  if (!ok) {
    sendError(409, error);
    return;
  }
  sendOk(requested + " accepted");
}

void handlePrinterQuery() {
  if (jobRunner.busy() || printerBridge.pending()) {
    sendError(409, "Printer UART is busy.");
    return;
  }
  const auto validation = plotter::protocol::validateQuery(
      std::string(server.arg("command").c_str()));
  if (!validation.accepted || validation.empty) {
    sendError(400, validation.reason.c_str());
    return;
  }
  if (!printerBridge.sendCommand(validation.command.c_str())) {
    sendError(409, "UART bridge refused the query.");
    return;
  }
  sendOk("Query accepted.");
}

void handleWifiSave() {
  if (jobRunner.busy()) {
    sendError(409, "Do not restart networking while a hardware job is active.");
    return;
  }
  const String ssid = server.arg("ssid");
  const String password = server.arg("password");
  if (ssid.length() > 32 || password.length() > 64) {
    sendError(400, "Wi-Fi credentials exceed supported lengths.");
    return;
  }
  preferences.putString("ssid", ssid);
  preferences.putString("password", password);
  sendOk("Wi-Fi configuration saved; restarting.");
  delay(350);
  ESP.restart();
}

void configureRoutes() {
  server.on("/", HTTP_GET, []() {
    server.sendHeader("Cache-Control", "no-store");
    server.send_P(200, "text/html", plotter::web::kIndexHtml);
  });
  server.on("/generate_204", HTTP_GET, []() { server.send_P(200, "text/html", plotter::web::kIndexHtml); });
  server.on("/hotspot-detect.html", HTTP_GET, []() { server.send_P(200, "text/html", plotter::web::kIndexHtml); });
  server.on("/fwlink", HTTP_GET, []() { server.send_P(200, "text/html", plotter::web::kIndexHtml); });
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/job", HTTP_POST, finishUploadRequest, handleUploadChunk);
  server.on("/api/job/start", HTTP_POST, []() { handleJobAction("start"); });
  server.on("/api/job/pause", HTTP_POST, []() { handleJobAction("pause"); });
  server.on("/api/job/resume", HTTP_POST, []() { handleJobAction("resume"); });
  server.on("/api/job/cancel", HTTP_POST, []() { handleJobAction("cancel"); });
  server.on("/api/emergency", HTTP_POST, []() {
    jobRunner.emergencyStop();
    sendOk("M112 sent. Reset the Printrboard before continuing.");
  });
  server.on("/api/printer/query", HTTP_POST, handlePrinterQuery);
  server.on("/api/wifi", HTTP_POST, handleWifiSave);
  server.onNotFound([]() {
    server.sendHeader("Location", "http://192.168.4.1/", true);
    server.send(302, "text/plain", "");
  });
  server.begin();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(250);

  statusPixel.begin();
  statusPixel.clear();
  statusPixel.show();
  setPixel(0, 30, 160);

  preferences.begin("plotter", false);
  if (!LittleFS.begin(true)) {
    setPixel(220, 0, 20);
    Serial.println("LittleFS failed to mount.");
  }

  printerBridge.begin();
  configureWifi();
  configureRoutes();

  Serial.println();
  Serial.println("Printrbot ESP32 bridge started.");
  Serial.print("Setup Wi-Fi: ");
  Serial.println(plotter::config::kAccessPointSsid);
  Serial.print("Setup password: ");
  Serial.println(plotter::config::kAccessPointPassword);
  Serial.println("Open http://192.168.4.1 or http://printrbot.local");

  printerBridge.sendCommand("M115");
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
  printerBridge.poll();
  jobRunner.tick();
  updateStatusPixel();
  delay(2);
}
