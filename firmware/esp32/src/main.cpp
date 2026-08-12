#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <esp_system.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>

#include <cstdio>
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
bool uploadDraftMode = false;
std::uint32_t lastLedUpdateMs = 0;
String httpUser = "admin";
String httpPassword;
String renderServerUrl;

String generateHttpPassword() {
  String password;
  password.reserve(32);
  for (int i = 0; i < 4; ++i) {
    const std::uint32_t value = esp_random();
    char chunk[9];
    std::snprintf(chunk, sizeof(chunk), "%08lx", static_cast<unsigned long>(value));
    password += chunk;
  }
  return password;
}

void configureHttpAuthentication() {
  httpUser = preferences.getString("http_user", "admin");
  if (httpUser.isEmpty()) httpUser = "admin";
  httpPassword = preferences.getString("http_pass", "");
  if (httpPassword.length() < 16) {
    httpPassword = generateHttpPassword();
    preferences.putString("http_user", httpUser);
    preferences.putString("http_pass", httpPassword);
    Serial.println("Generated new bridge HTTP credentials.");
    Serial.print("Username: ");
    Serial.println(httpUser);
    Serial.print("Password: ");
    Serial.println(httpPassword);
    Serial.println("Store this password securely; it is not shown by the web UI.");
  }
}

bool requireHttpAuthentication() {
  if (server.authenticate(httpUser.c_str(), httpPassword.c_str())) return true;
  server.requestAuthentication(BASIC_AUTH, "Printrbot Bridge", "Authentication required");
  return false;
}

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

String renderUrl(const char* path) {
  String base = renderServerUrl;
  while (base.endsWith("/")) base.remove(base.length() - 1);
  return base + path;
}

bool renderServerConfigured() {
  return renderServerUrl.startsWith("http://") && renderServerUrl.length() <= 120;
}

void proxyPythonGet(const char* path, const char* contentType) {
  if (!renderServerConfigured()) {
    sendError(503, "Python render server is not configured.");
    return;
  }
  WiFiClient client;
  HTTPClient request;
  if (!request.begin(client, renderUrl(path))) {
    sendError(502, "Could not connect to the Python render server.");
    return;
  }
  request.setTimeout(30000);
  const int status = request.GET();
  const String body = request.getString();
  request.end();
  if (status <= 0) {
    sendError(502, "Python render server did not respond.");
    return;
  }
  server.sendHeader("Cache-Control", "no-store");
  server.send(status, contentType, body);
}

void proxyPythonJsonPost(const char* path) {
  if (!renderServerConfigured()) {
    sendError(503, "Python render server is not configured.");
    return;
  }
  const String body = server.arg("plain");
  if (body.isEmpty() || body.length() > 32000) {
    sendError(400, "Expected a non-empty JSON request under 32 KiB.");
    return;
  }
  WiFiClient client;
  HTTPClient request;
  if (!request.begin(client, renderUrl(path))) {
    sendError(502, "Could not connect to the Python render server.");
    return;
  }
  request.setTimeout(60000);
  request.addHeader("Content-Type", "application/json");
  String payload = body;
  const int status = request.POST(reinterpret_cast<uint8_t*>(payload.begin()), payload.length());
  const String response = request.getString();
  request.end();
  if (status <= 0) {
    sendError(502, "Python render server did not respond.");
    return;
  }
  server.sendHeader("Cache-Control", "no-store");
  server.send(status, "application/json", response);
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
  json += "\"render_server\":\"" + jsonEscape(renderServerUrl) + "\",";
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

    if (!uploadDraftMode && server.hasArg("safe_z_up_mm")) {
      const float requestedSafeZ = server.arg("safe_z_up_mm").toFloat();
      if (!jobRunner.setSafeZUpMm(requestedSafeZ)) {
        uploadFailed = true;
        uploadError = "Pen lift height must be at least 5 mm and within the Z limit.";
        return;
      }
    }

    if (jobRunner.busy()) {
      uploadFailed = true;
      uploadError = "Cannot replace a job while hardware motion is active.";
      return;
    }

    if (uploadFile) uploadFile.close();
    const char* uploadPath = uploadDraftMode ? plotter::config::kDraftPath : plotter::config::kJobPath;
    LittleFS.remove(uploadPath);
    uploadFile = LittleFS.open(uploadPath, FILE_WRITE);
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
      LittleFS.remove(uploadDraftMode ? plotter::config::kDraftPath : plotter::config::kJobPath);
      return;
    }
    if (!uploadFile || uploadFile.write(upload.buf, upload.currentSize) != upload.currentSize) {
      uploadFailed = true;
      uploadError = "Failed while writing the uploaded job to flash.";
      if (uploadFile) uploadFile.close();
      LittleFS.remove(uploadDraftMode ? plotter::config::kDraftPath : plotter::config::kJobPath);
      return;
    }
    uploadBytes += upload.currentSize;
    return;
  }

  if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) uploadFile.close();
    if (uploadFailed) return;
    if (!uploadDraftMode) {
      String error;
      if (!jobRunner.loadStoredJob(LittleFS, plotter::config::kJobPath, error)) {
        uploadFailed = true;
        uploadError = error;
        LittleFS.remove(plotter::config::kJobPath);
      } else {
        LittleFS.remove(plotter::config::kDraftPath);
      }
    }
    return;
  }

  if (upload.status == UPLOAD_FILE_ABORTED) {
    uploadFailed = true;
    uploadError = "Upload was aborted.";
    if (uploadFile) uploadFile.close();
    LittleFS.remove(uploadDraftMode ? plotter::config::kDraftPath : plotter::config::kJobPath);
  }
}

void finishUploadRequest() {
  if (uploadFile) uploadFile.close();
  if (uploadFailed) {
    sendError(400, uploadError);
    return;
  }
  sendOk(uploadDraftMode ? "G-code draft uploaded." : "Job validated and stored.");
}

void handleFinalUploadChunk() { uploadDraftMode = false; handleUploadChunk(); }
void handleDraftUploadChunk() { uploadDraftMode = true; handleUploadChunk(); }

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

void handleRenderServerSave() {
  if (jobRunner.busy()) {
    sendError(409, "Do not change the render server while a hardware job is active.");
    return;
  }
  String url = server.arg("url");
  url.trim();
  while (url.endsWith("/")) url.remove(url.length() - 1);
  if (!url.isEmpty() && (!url.startsWith("http://") || url.length() > 120)) {
    sendError(400, "Use an HTTP URL such as http://192.168.1.42:8000.");
    return;
  }
  renderServerUrl = url;
  preferences.putString("render_url", renderServerUrl);
  sendOk(renderServerUrl.isEmpty() ? "Python render server cleared." : "Python render server saved.");
}

void configureRoutes() {
  server.on("/", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    server.sendHeader("Cache-Control", "no-store");
    server.send_P(200, "text/html", plotter::web::kIndexHtml);
  });
  server.on("/write", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    proxyPythonGet("/", "text/html");
  });
  server.on("/generate_204", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    server.send_P(200, "text/html", plotter::web::kIndexHtml);
  });
  server.on("/hotspot-detect.html", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    server.send_P(200, "text/html", plotter::web::kIndexHtml);
  });
  server.on("/fwlink", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    server.send_P(200, "text/html", plotter::web::kIndexHtml);
  });
  server.on("/api/status", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    handleStatus();
  });
  server.on("/api/render", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    proxyPythonJsonPost("/api/render");
  });
  server.on("/api/fonts", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    proxyPythonGet("/api/fonts", "application/json");
  });
  server.on("/api/font-library", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    proxyPythonGet("/api/font-library", "application/json");
  });
  server.on("/api/handwriting/status", HTTP_GET, []() {
    if (!requireHttpAuthentication()) return;
    proxyPythonGet("/api/handwriting/status", "application/json");
  });
  server.on("/api/job", HTTP_POST,
            []() { if (requireHttpAuthentication()) finishUploadRequest(); },
            []() { if (requireHttpAuthentication()) handleFinalUploadChunk(); });
  server.on("/api/job/draft", HTTP_POST,
            []() { if (requireHttpAuthentication()) finishUploadRequest(); },
            []() { if (requireHttpAuthentication()) handleDraftUploadChunk(); });
  server.on("/api/job/start", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleJobAction("start");
  });
  server.on("/api/job/pause", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleJobAction("pause");
  });
  server.on("/api/job/resume", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleJobAction("resume");
  });
  server.on("/api/job/cancel", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleJobAction("cancel");
  });
  server.on("/api/emergency", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    jobRunner.emergencyStop();
    sendOk("M112 sent. Reset the Printrboard before continuing.");
  });
  server.on("/api/printer/query", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handlePrinterQuery();
  });
  server.on("/api/wifi", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleWifiSave();
  });
  server.on("/api/render-server", HTTP_POST, []() {
    if (!requireHttpAuthentication()) return;
    handleRenderServerSave();
  });
  server.onNotFound([]() {
    if (!requireHttpAuthentication()) return;
    server.sendHeader("Location", "http://192.168.4.1/", true);
    server.send(302, "text/plain", "");
  });
  server.begin();
}

}  // namespace

void setup() {
  delay(250);

  Serial.begin(115200);

  statusPixel.begin();
  statusPixel.clear();
  statusPixel.show();
  setPixel(0, 30, 160);

  preferences.begin("plotter", false);
  renderServerUrl = preferences.getString("render_url", "");
  configureHttpAuthentication();
  if (!LittleFS.begin(true)) {
    setPixel(220, 0, 20);
  }

  printerBridge.begin();
  configureWifi();
  configureRoutes();
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
