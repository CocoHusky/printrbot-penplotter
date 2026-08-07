#pragma once

#include <Arduino.h>
#include <FS.h>

#include "printer_bridge.h"

namespace plotter {

enum class JobState {
  Idle,
  Ready,
  Running,
  Paused,
  Cancelling,
  Cancelled,
  Completed,
  Failed,
  Emergency,
};

class JobRunner {
 public:
  explicit JobRunner(PrinterBridge& bridge);

  bool loadStoredJob(fs::FS& filesystem, const char* path, String& error);
  bool start(fs::FS& filesystem, String& error);
  bool pause(String& error);
  bool resume(String& error);
  bool cancel(String& error);
  void emergencyStop();
  void tick();

  bool busy() const;
  JobState state() const { return state_; }
  const char* stateName() const;
  std::size_t totalCommands() const { return totalCommands_; }
  std::size_t completedCommands() const { return completedCommands_; }
  std::size_t jobBytes() const { return jobBytes_; }
  const String& lastError() const { return lastError_; }
  const String& activeCommand() const { return activeCommand_; }
  float progressPercent() const;

 private:
  bool readNextCommand(String& command, String& error);
  void beginSafeStop(JobState finalState, const String& reason);
  void driveSafeStop();
  void finish(JobState state, const String& reason = "");

  PrinterBridge& bridge_;
  fs::FS* filesystem_{nullptr};
  String jobPath_;
  File jobFile_;
  JobState state_{JobState::Idle};
  JobState stopFinalState_{JobState::Cancelled};
  std::size_t totalCommands_{0};
  std::size_t completedCommands_{0};
  std::size_t jobBytes_{0};
  String lastError_;
  String activeCommand_;
  bool pauseRequested_{false};
  bool stopping_{false};
  int stopStage_{0};
};

}  // namespace plotter
