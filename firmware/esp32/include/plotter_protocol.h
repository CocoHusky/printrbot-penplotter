#pragma once

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <string>
#include <string_view>
#include <unordered_set>

#include "bridge_config.h"

namespace plotter::protocol {

struct ValidationResult {
  bool accepted{false};
  bool empty{false};
  std::string command;
  std::string reason;
};

struct JobValidationState {
  bool millimeters{false};
  bool absolutePositioning{false};
  bool homedX{false};
  bool homedY{false};
  bool homedZ{false};
  bool zPositionKnown{false};
  float zPositionMm{0.0F};
  bool sawAxisMotion{false};
  bool sawXyMotion{false};
};

inline std::string trim(std::string value) {
  const auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
    return std::isspace(c) != 0;
  });
  const auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
    return std::isspace(c) != 0;
  }).base();
  if (first >= last) return {};
  return std::string(first, last);
}

inline std::string uppercase(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::toupper(c));
  });
  return value;
}

inline std::string stripComments(std::string line) {
  const auto semicolon = line.find(';');
  if (semicolon != std::string::npos) line.erase(semicolon);

  std::string result;
  result.reserve(line.size());
  bool inParenthetical = false;
  for (char c : line) {
    if (c == '(') {
      inParenthetical = true;
      continue;
    }
    if (c == ')') {
      inParenthetical = false;
      continue;
    }
    if (!inParenthetical) result.push_back(c);
  }
  return trim(result);
}

inline std::string commandToken(const std::string& command) {
  std::size_t start = 0;
  while (start < command.size() && std::isspace(static_cast<unsigned char>(command[start]))) ++start;
  std::size_t end = start;
  while (end < command.size() && !std::isspace(static_cast<unsigned char>(command[end]))) ++end;
  return uppercase(command.substr(start, end - start));
}

inline bool hasWord(const std::string& command, char letter) {
  const std::string upper = uppercase(command);
  for (std::size_t i = 0; i < upper.size(); ++i) {
    if (upper[i] != letter) continue;
    if (i > 0 && std::isalpha(static_cast<unsigned char>(upper[i - 1]))) continue;
    return true;
  }
  return false;
}

inline bool hasAxisParameter(const std::string& command, char axis) {
  const std::string upper = uppercase(command);
  for (std::size_t i = 0; i < upper.size(); ++i) {
    if (upper[i] != axis) continue;
    if (i > 0 && std::isalpha(static_cast<unsigned char>(upper[i - 1]))) continue;
    if (i + 1 < upper.size()) {
      const char next = upper[i + 1];
      if (std::isdigit(static_cast<unsigned char>(next)) || next == '+' || next == '-' || next == '.') {
        return true;
      }
    }
  }
  return false;
}

inline bool parseParameter(const std::string& command, char letter, float& value) {
  const std::string upper = uppercase(command);
  for (std::size_t i = 0; i < upper.size(); ++i) {
    if (upper[i] != letter) continue;
    if (i > 0 && std::isalpha(static_cast<unsigned char>(upper[i - 1]))) continue;
    if (i + 1 >= upper.size()) return false;

    const char* start = upper.c_str() + i + 1;
    char* end = nullptr;
    errno = 0;
    const float parsed = std::strtof(start, &end);
    if (end == start || errno == ERANGE || !std::isfinite(parsed)) return false;
    value = parsed;
    return true;
  }
  return false;
}

inline bool forbiddenToken(const std::string& token) {
  static const std::unordered_set<std::string> blocked = {
      "M82", "M83", "M104", "M109", "M140", "M141", "M190", "M191",
      "M200", "M221", "M302", "M303", "M600", "M701", "M702", "M112"};
  if (blocked.count(token) != 0) return true;
  return !token.empty() && token.front() == 'T';
}

inline bool queryAllowed(const std::string& token) {
  static const std::unordered_set<std::string> allowed = {
      "M105", "M114", "M115", "M119", "M503"};
  return allowed.count(token) != 0;
}

inline bool jobTokenAllowed(const std::string& token) {
  static const std::unordered_set<std::string> allowed = {
      "G0", "G00", "G1", "G01", "G21", "G28", "G90", "M400",
      "M105", "M114", "M115", "M119", "M503"};
  return allowed.count(token) != 0;
}

inline ValidationResult validateJobLine(std::string line) {
  ValidationResult result;
  result.command = stripComments(std::move(line));
  if (result.command.empty()) {
    result.accepted = true;
    result.empty = true;
    return result;
  }

  if (result.command.size() > 256) {
    result.reason = "command exceeds 256 characters";
    return result;
  }

  const std::string token = commandToken(result.command);
  if (forbiddenToken(token)) {
    result.reason = "forbidden heater, extrusion, emergency, or tool command: " + token;
    return result;
  }

  if (!jobTokenAllowed(token)) {
    result.reason = "unsupported command in guarded plot job: " + token;
    return result;
  }

  if ((token == "G0" || token == "G00" || token == "G1" || token == "G01") &&
      hasAxisParameter(result.command, 'E')) {
    result.reason = "extrusion-axis parameter E is forbidden";
    return result;
  }

  result.accepted = true;
  return result;
}

inline ValidationResult validateJobSequenceLine(std::string line, JobValidationState& state) {
  ValidationResult result = validateJobLine(std::move(line));
  if (!result.accepted || result.empty) return result;

  const std::string token = commandToken(result.command);
  if (queryAllowed(token)) {
    result.accepted = false;
    result.reason = "status queries are not allowed inside a stored motion job";
    return result;
  }

  if (token == "G21") {
    state.millimeters = true;
    return result;
  }
  if (token == "G90") {
    state.absolutePositioning = true;
    return result;
  }
  if (token == "M400") return result;

  if (token == "G28") {
    const bool specifiesX = hasWord(result.command, 'X');
    const bool specifiesY = hasWord(result.command, 'Y');
    const bool specifiesZ = hasWord(result.command, 'Z');
    const bool homesAll = !specifiesX && !specifiesY && !specifiesZ;

    if (homesAll || specifiesX) state.homedX = true;
    if (homesAll || specifiesY) state.homedY = true;
    if (homesAll || specifiesZ) {
      state.homedZ = true;
      state.zPositionKnown = true;
      state.zPositionMm = config::kMachineZMinMm;
    }
    return result;
  }

  const bool isMove = token == "G0" || token == "G00" || token == "G1" || token == "G01";
  if (!isMove) return result;

  if (!state.millimeters) {
    result.accepted = false;
    result.reason = "G21 millimeter mode is required before coordinate motion";
    return result;
  }
  if (!state.absolutePositioning) {
    result.accepted = false;
    result.reason = "G90 absolute positioning is required before coordinate motion";
    return result;
  }

  const bool hasX = hasWord(result.command, 'X');
  const bool hasY = hasWord(result.command, 'Y');
  const bool hasZ = hasWord(result.command, 'Z');
  const bool hasF = hasWord(result.command, 'F');
  if (!hasX && !hasY && !hasZ) {
    result.accepted = false;
    result.reason = "motion command must contain X, Y, or Z";
    return result;
  }
  if (hasZ && (hasX || hasY)) {
    result.accepted = false;
    result.reason = "simultaneous XY and Z motion is not allowed in guarded plot jobs";
    return result;
  }

  float x = 0.0F;
  float y = 0.0F;
  float z = 0.0F;
  float feed = 0.0F;
  if (hasX && !parseParameter(result.command, 'X', x)) {
    result.accepted = false;
    result.reason = "X parameter is missing a finite numeric value";
    return result;
  }
  if (hasY && !parseParameter(result.command, 'Y', y)) {
    result.accepted = false;
    result.reason = "Y parameter is missing a finite numeric value";
    return result;
  }
  if (hasZ && !parseParameter(result.command, 'Z', z)) {
    result.accepted = false;
    result.reason = "Z parameter is missing a finite numeric value";
    return result;
  }
  if (hasF && (!parseParameter(result.command, 'F', feed) || feed <= 0.0F)) {
    result.accepted = false;
    result.reason = "feed parameter F must be a finite positive value";
    return result;
  }

  constexpr float tolerance = 0.01F;
  if (hasX && (x < config::kMachineXMinMm - tolerance || x > config::kMachineXMaxMm + tolerance)) {
    result.accepted = false;
    result.reason = "X coordinate is outside configured machine limits";
    return result;
  }
  if (hasY && (y < config::kMachineYMinMm - tolerance || y > config::kMachineYMaxMm + tolerance)) {
    result.accepted = false;
    result.reason = "Y coordinate is outside configured machine limits";
    return result;
  }
  if (hasZ && (z < config::kMachineZMinMm - tolerance || z > config::kMachineZMaxMm + tolerance)) {
    result.accepted = false;
    result.reason = "Z coordinate is outside configured machine limits";
    return result;
  }

  if (hasX && !state.homedX) {
    result.accepted = false;
    result.reason = "X motion requires G28 X or G28 earlier in the same job";
    return result;
  }
  if (hasY && !state.homedY) {
    result.accepted = false;
    result.reason = "Y motion requires G28 Y or G28 earlier in the same job";
    return result;
  }
  if (hasZ && !state.homedZ) {
    result.accepted = false;
    result.reason = "Z motion requires G28 Z or G28 earlier in the same job";
    return result;
  }
  if ((hasX || hasY) && !state.homedZ) {
    result.accepted = false;
    result.reason = "XY motion requires Z homing earlier in the same job";
    return result;
  }

  if (hasF) {
    const float maximumFeed = hasZ ? config::kMaximumZFeedMmMin : config::kMaximumXYFeedMmMin;
    if (feed > maximumFeed + tolerance) {
      result.accepted = false;
      result.reason = hasZ ? "Z feed exceeds configured machine maximum"
                           : "XY feed exceeds configured machine maximum";
      return result;
    }
  }

  if ((hasX || hasY) && !state.sawXyMotion) {
    if (!state.zPositionKnown || state.zPositionMm < config::kSafeZUpMm - tolerance) {
      result.accepted = false;
      result.reason = "first XY motion requires the pen to be raised to the configured safe Z first";
      return result;
    }
  }

  if (hasZ) {
    state.zPositionKnown = true;
    state.zPositionMm = z;
  }
  state.sawAxisMotion = true;
  if (hasX || hasY) state.sawXyMotion = true;
  return result;
}

inline ValidationResult validateJobCompletion(const JobValidationState& state) {
  ValidationResult result;
  result.accepted = true;

  // Home-only diagnostic jobs are valid. Once a job performs XY plotting motion,
  // it must leave the machine in the known safe pen-up state.
  if (state.sawXyMotion) {
    if (!state.homedX || !state.homedY || !state.homedZ) {
      result.accepted = false;
      result.reason = "plotting motion requires X, Y, and Z to be homed in the same job";
      return result;
    }
    if (!state.zPositionKnown || state.zPositionMm < config::kSafeZUpMm - 0.01F) {
      result.accepted = false;
      result.reason = "plotting job must finish with the pen at or above the configured safe Z";
      return result;
    }
  }
  return result;
}

inline ValidationResult validateQuery(std::string line) {
  ValidationResult result = validateJobLine(std::move(line));
  if (!result.accepted || result.empty) return result;
  const std::string token = commandToken(result.command);
  if (!queryAllowed(token)) {
    result.accepted = false;
    result.reason = "only non-moving status queries are accepted by this endpoint";
  }
  return result;
}

}  // namespace plotter::protocol
