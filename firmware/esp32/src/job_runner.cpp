#include "job_runner.h"

#include <LittleFS.h>

#include <string>

#include "bridge_config.h"
#include "plotter_protocol.h"

namespace plotter {

JobRunner::JobRunner(PrinterBridge& bridge) : bridge_(bridge) {}

bool JobRunner::setSafeZUpMm(float heightMm) {
  if (!isfinite(heightMm) || heightMm < config::kSafeZUpMm ||
      heightMm > config::kMachineZMaxMm) {
    return false;
  }
  safeZUpMm_ = heightMm;
  return true;
}

bool JobRunner::busy() const {
  return state_ == JobState::Running || state_ == JobState::Paused ||
         state_ == JobState::Cancelling || stopping_;
}

const char* JobRunner::stateName() const {
  switch (state_) {
    case JobState::Idle: return "idle";
    case JobState::Ready: return "ready";
    case JobState::Running: return "running";
    case JobState::Paused: return "paused";
    case JobState::Cancelling: return "cancelling";
    case JobState::Cancelled: return "cancelled";
    case JobState::Completed: return "completed";
    case JobState::Failed: return "failed";
    case JobState::Emergency: return "emergency";
  }
  return "unknown";
}

float JobRunner::progressPercent() const {
  if (totalCommands_ == 0) return 0.0F;
  return 100.0F * static_cast<float>(completedCommands_) /
         static_cast<float>(totalCommands_);
}

bool JobRunner::loadStoredJob(fs::FS& filesystem, const char* path, String& error) {
  if (busy()) {
    error = "A hardware job is active.";
    return false;
  }

  File file = filesystem.open(path, FILE_READ);
  if (!file) {
    error = "Uploaded G-code file could not be opened.";
    return false;
  }

  const std::size_t bytes = file.size();
  if (bytes == 0 || bytes > config::kMaximumJobBytes) {
    file.close();
    error = "Job must be between 1 byte and the configured 512 KiB limit.";
    return false;
  }

  std::size_t commandCount = 0;
  std::size_t lineNumber = 0;
  protocol::JobValidationState validationState;
  if (config::kForceHomeBeforeEveryJob) {
    const auto home = protocol::validateJobSequenceLine("G28", validationState);
    const auto wait = protocol::validateJobSequenceLine("M400", validationState);
    if (!home.accepted || !wait.accepted) {
      file.close();
      error = "Built-in pre-job homing sequence is invalid: " +
              String((!home.accepted ? home.reason : wait.reason).c_str());
      return false;
    }
    commandCount += 2;
  }
  while (file.available()) {
    String line = file.readStringUntil('\n');
    ++lineNumber;
    const auto validation = protocol::validateJobSequenceLine(
        std::string(line.c_str()), validationState, safeZUpMm_);
    if (!validation.accepted) {
      file.close();
      error = "Line " + String(lineNumber) + " rejected: " + validation.reason.c_str();
      return false;
    }
    if (!validation.empty) {
      ++commandCount;
      if (commandCount > config::kMaximumCommands) {
        file.close();
        error = "Job exceeds the configured command-count limit.";
        return false;
      }
    }
  }

  const auto completion = protocol::validateJobCompletion(validationState, safeZUpMm_);
  if (!completion.accepted) {
    file.close();
    error = "Job rejected: " + String(completion.reason.c_str());
    return false;
  }
  file.close();

  if (commandCount == 0) {
    error = "Job contains no executable commands.";
    return false;
  }

  filesystem_ = &filesystem;
  jobPath_ = path;
  totalCommands_ = commandCount;
  completedCommands_ = 0;
  jobBytes_ = bytes;
  lastError_ = "";
  activeCommand_ = "";
  pauseRequested_ = false;
  stopping_ = false;
  stopStage_ = 0;
  startupStage_ = config::kForceHomeBeforeEveryJob ? 0 : 2;
  state_ = JobState::Ready;
  return true;
}

bool JobRunner::start(fs::FS& filesystem, String& error) {
  if (state_ != JobState::Ready && state_ != JobState::Completed &&
      state_ != JobState::Cancelled && state_ != JobState::Failed) {
    error = "No validated job is ready to start.";
    return false;
  }
  if (jobPath_.isEmpty()) {
    error = "No stored job path is available.";
    return false;
  }

  if (jobFile_) jobFile_.close();
  jobFile_ = filesystem.open(jobPath_, FILE_READ);
  if (!jobFile_) {
    error = "Stored job could not be reopened.";
    return false;
  }

  filesystem_ = &filesystem;
  completedCommands_ = 0;
  activeCommand_ = "";
  lastError_ = "";
  pauseRequested_ = false;
  stopping_ = false;
  stopStage_ = 0;
  startupStage_ = config::kForceHomeBeforeEveryJob ? 0 : 2;
  state_ = JobState::Running;
  return true;
}

bool JobRunner::pause(String& error) {
  if (state_ != JobState::Running) {
    error = "Only a running job can be paused.";
    return false;
  }
  pauseRequested_ = true;
  if (!bridge_.pending()) {
    state_ = JobState::Paused;
    pauseRequested_ = false;
  }
  return true;
}

bool JobRunner::resume(String& error) {
  if (state_ != JobState::Paused) {
    error = "Only a paused job can be resumed.";
    return false;
  }
  pauseRequested_ = false;
  state_ = JobState::Running;
  return true;
}

bool JobRunner::cancel(String& error) {
  if (state_ == JobState::Ready) {
    finish(JobState::Cancelled, "Cancelled before starting.");
    return true;
  }
  if (state_ != JobState::Running && state_ != JobState::Paused) {
    error = "Only a ready, running, or paused job can be cancelled.";
    return false;
  }
  beginSafeStop(JobState::Cancelled, "Orderly cancellation requested.");
  return true;
}

void JobRunner::emergencyStop() {
  if (jobFile_) jobFile_.close();
  bridge_.emergencyStop();
  stopping_ = false;
  pauseRequested_ = false;
  state_ = JobState::Emergency;
  lastError_ = "M112 emergency stop sent. Reset the Printrboard before continuing.";
}

bool JobRunner::readNextCommand(String& command, String& error) {
  if (startupStage_ == 0) {
    startupStage_ = 1;
    command = "G28";
    return true;
  }
  if (startupStage_ == 1) {
    startupStage_ = 2;
    command = "M400";
    return true;
  }
  while (jobFile_ && jobFile_.available()) {
    String line = jobFile_.readStringUntil('\n');
    const auto validation = protocol::validateJobLine(std::string(line.c_str()));
    if (!validation.accepted) {
      error = validation.reason.c_str();
      return false;
    }
    if (validation.empty) continue;
    command = validation.command.c_str();
    return true;
  }
  command = "";
  return true;
}

void JobRunner::beginSafeStop(JobState finalState, const String& reason) {
  stopFinalState_ = finalState;
  lastError_ = reason;
  stopping_ = true;
  stopStage_ = bridge_.pending() ? -1 : 0;
  state_ = JobState::Cancelling;
  pauseRequested_ = false;
}

void JobRunner::driveSafeStop() {
  if (!stopping_ || bridge_.pending() || stopStage_ < 0) return;

  String command;
  switch (stopStage_) {
    case 0:
      command = "M400";
      break;
    case 1:
      command = "G0 Z" + String(safeZUpMm_, 3) +
                " F" + String(config::kSafeZFeedMmMin);
      break;
    case 2:
      command = "M400";
      break;
    default:
      finish(stopFinalState_, lastError_);
      return;
  }

  if (bridge_.sendCommand(command)) {
    activeCommand_ = command;
  }
}

void JobRunner::finish(JobState state, const String& reason) {
  if (jobFile_) jobFile_.close();
  state_ = state;
  stopping_ = false;
  pauseRequested_ = false;
  activeCommand_ = "";
  if (!reason.isEmpty()) lastError_ = reason;
}

void JobRunner::tick() {
  const BridgeEvent event = bridge_.takeEvent();
  if (event.type != BridgeEventType::None) {
    if (stopping_) {
      if (event.type == BridgeEventType::Ok) {
        if (stopStage_ < 0) {
          stopStage_ = 0;
        } else {
          ++stopStage_;
        }
      } else {
        finish(JobState::Failed, "Safe-stop sequence failed: " + event.line);
      }
    } else if (state_ == JobState::Running) {
      if (event.type == BridgeEventType::Ok) {
        ++completedCommands_;
        activeCommand_ = "";
        if (pauseRequested_) {
          pauseRequested_ = false;
          state_ = JobState::Paused;
        }
      } else {
        beginSafeStop(JobState::Failed, "Marlin communication failed: " + event.line);
      }
    }
  }

  if (stopping_) {
    driveSafeStop();
    return;
  }

  if (state_ != JobState::Running || bridge_.pending()) return;

  String command;
  String error;
  if (!readNextCommand(command, error)) {
    beginSafeStop(JobState::Failed, "Stored job became invalid: " + error);
    return;
  }

  if (command.isEmpty()) {
    finish(JobState::Completed);
    return;
  }

  if (!bridge_.sendCommand(command)) {
    beginSafeStop(JobState::Failed, "UART bridge refused the next command.");
    return;
  }
  activeCommand_ = command;
}

}  // namespace plotter
