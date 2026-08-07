#pragma once

#include <algorithm>
#include <cctype>
#include <string>
#include <string_view>
#include <unordered_set>

namespace plotter::protocol {

struct ValidationResult {
  bool accepted{false};
  bool empty{false};
  std::string command;
  std::string reason;
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

  if ((token == "G0" || token == "G00" || token == "G1" || token == "G01") &&
      hasAxisParameter(result.command, 'E')) {
    result.reason = "extrusion-axis parameter E is forbidden";
    return result;
  }

  result.accepted = true;
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
