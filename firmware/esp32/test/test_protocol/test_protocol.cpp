#include <cstring>
#include <unity.h>

#include "plotter_protocol.h"

using plotter::protocol::JobValidationState;
using plotter::protocol::validateJobCompletion;
using plotter::protocol::validateJobLine;
using plotter::protocol::validateJobSequenceLine;
using plotter::protocol::validateQuery;

void setUp() {}
void tearDown() {}

void test_comments_and_blank_lines_are_skipped() {
  const auto blank = validateJobLine("  ; only a comment");
  TEST_ASSERT_TRUE(blank.accepted);
  TEST_ASSERT_TRUE(blank.empty);

  const auto command = validateJobLine("G1 X10 Y20 ; draw line");
  TEST_ASSERT_TRUE(command.accepted);
  TEST_ASSERT_FALSE(command.empty);
  TEST_ASSERT_EQUAL_STRING("G1 X10 Y20", command.command.c_str());
}

void test_normal_plotter_commands_are_allowed() {
  TEST_ASSERT_TRUE(validateJobLine("G21").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G90").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G28").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G28 X").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G28 X Y").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G0 X4.0 Y5.0 F3000").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G1 X8 Y9 F1200").accepted);
  TEST_ASSERT_TRUE(validateJobLine("G0 Z5 F300").accepted);
  TEST_ASSERT_TRUE(validateJobLine("M400").accepted);
}

void test_heater_extrusion_and_tool_commands_are_blocked() {
  TEST_ASSERT_FALSE(validateJobLine("M104 S200").accepted);
  TEST_ASSERT_FALSE(validateJobLine("M109 S200").accepted);
  TEST_ASSERT_FALSE(validateJobLine("M140 S60").accepted);
  TEST_ASSERT_FALSE(validateJobLine("M190 S60").accepted);
  TEST_ASSERT_FALSE(validateJobLine("M82").accepted);
  TEST_ASSERT_FALSE(validateJobLine("T0").accepted);
  TEST_ASSERT_FALSE(validateJobLine("G1 X1 E4").accepted);
  TEST_ASSERT_FALSE(validateJobLine("G1 E-2").accepted);
}

void test_embedded_emergency_stop_is_blocked() {
  const auto result = validateJobLine("M112");
  TEST_ASSERT_FALSE(result.accepted);
  TEST_ASSERT_NOT_NULL(strstr(result.reason.c_str(), "forbidden"));
}

void test_unknown_and_coordinate_changing_commands_are_blocked() {
  TEST_ASSERT_FALSE(validateJobLine("G20").accepted);
  TEST_ASSERT_FALSE(validateJobLine("G91").accepted);
  TEST_ASSERT_FALSE(validateJobLine("G92 X0").accepted);
  TEST_ASSERT_FALSE(validateJobLine("G2 X10 Y10 I2 J2").accepted);
  TEST_ASSERT_FALSE(validateJobLine("M500").accepted);
}

void test_query_endpoint_only_allows_nonmoving_status_commands() {
  TEST_ASSERT_TRUE(validateQuery("M115").accepted);
  TEST_ASSERT_TRUE(validateQuery("M119").accepted);
  TEST_ASSERT_TRUE(validateQuery("M114").accepted);
  TEST_ASSERT_TRUE(validateQuery("M503").accepted);
  TEST_ASSERT_FALSE(validateQuery("G28").accepted);
  TEST_ASSERT_FALSE(validateQuery("G0 X10").accepted);
}

void test_sequence_rejects_motion_without_homing() {
  JobValidationState state;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G21", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G90", state).accepted);
  const auto move = validateJobSequenceLine("G0 Z5 F120", state);
  TEST_ASSERT_FALSE(move.accepted);
  TEST_ASSERT_NOT_NULL(strstr(move.reason.c_str(), "G28 Z"));
}

void test_sequence_allows_home_only_axis_diagnostics() {
  JobValidationState state;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G28 X", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("M400", state).accepted);
  TEST_ASSERT_TRUE(validateJobCompletion(state).accepted);
}

void test_sequence_accepts_guarded_generated_plot_with_diagonal_xy() {
  JobValidationState state;
  const char* lines[] = {
      "G21", "G90", "M400", "G28", "M400",
      "G0 Z5 F120", "G0 X20 Y20 F1000", "G0 Z0 F120",
      "G1 X30 Y30 F600",  // simultaneous X+Y is a valid diagonal line
      "G0 Z5 F120", "M400", "G28 X Y", "M400"};
  for (const char* line : lines) {
    const auto result = validateJobSequenceLine(line, state);
    TEST_ASSERT_TRUE_MESSAGE(result.accepted, result.reason.c_str());
  }
  TEST_ASSERT_TRUE(validateJobCompletion(state).accepted);
}

void test_sequence_requires_safe_pen_up_before_first_xy() {
  JobValidationState state;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G21", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G90", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G28", state).accepted);
  const auto move = validateJobSequenceLine("G0 X20 Y20 F1000", state);
  TEST_ASSERT_FALSE(move.accepted);
  TEST_ASSERT_NOT_NULL(strstr(move.reason.c_str(), "safe Z"));
}

void test_sequence_requires_final_pen_up_after_plotting() {
  JobValidationState state;
  const char* lines[] = {
      "G21", "G90", "G28", "G0 Z5 F120", "G0 X20 Y20 F1000",
      "G0 Z0 F120", "G1 X30 Y30 F600", "G28 X Y"};
  for (const char* line : lines) {
    const auto result = validateJobSequenceLine(line, state);
    TEST_ASSERT_TRUE_MESSAGE(result.accepted, result.reason.c_str());
  }
  const auto completion = validateJobCompletion(state);
  TEST_ASSERT_FALSE(completion.accepted);
  TEST_ASSERT_NOT_NULL(strstr(completion.reason.c_str(), "finish"));
}

void test_sequence_requires_end_xy_rehome_after_plotting() {
  JobValidationState state;
  const char* lines[] = {
      "G21", "G90", "G28", "G0 Z5 F120", "G0 X20 Y20 F1000",
      "G0 Z0 F120", "G1 X30 Y30 F600", "G0 Z5 F120", "M400"};
  for (const char* line : lines) {
    const auto result = validateJobSequenceLine(line, state);
    TEST_ASSERT_TRUE_MESSAGE(result.accepted, result.reason.c_str());
  }
  const auto completion = validateJobCompletion(state);
  TEST_ASSERT_FALSE(completion.accepted);
  TEST_ASSERT_NOT_NULL(strstr(completion.reason.c_str(), "re-homing X/Y"));
}

void test_sequence_rejects_z_homing_after_plotting_motion() {
  JobValidationState state;
  const char* lines[] = {
      "G21", "G90", "G28", "G0 Z5 F120", "G0 X20 Y20 F1000",
      "G0 Z5 F120"};
  for (const char* line : lines) {
    const auto result = validateJobSequenceLine(line, state);
    TEST_ASSERT_TRUE_MESSAGE(result.accepted, result.reason.c_str());
  }
  const auto endHome = validateJobSequenceLine("G28", state);
  TEST_ASSERT_FALSE(endHome.accepted);
  TEST_ASSERT_NOT_NULL(strstr(endHome.reason.c_str(), "X/Y only"));
}

void test_sequence_rejects_out_of_bounds_and_excessive_feed() {
  JobValidationState boundsState;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G21", boundsState).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G90", boundsState).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G28", boundsState).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G0 Z5 F120", boundsState).accepted);
  TEST_ASSERT_FALSE(validateJobSequenceLine("G0 X200 Y20 F1000", boundsState).accepted);

  JobValidationState feedState;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G21", feedState).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G90", feedState).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G28", feedState).accepted);
  TEST_ASSERT_FALSE(validateJobSequenceLine("G0 Z5 F301", feedState).accepted);
}

void test_sequence_rejects_simultaneous_xy_and_z_motion_but_not_diagonal_xy() {
  JobValidationState state;
  TEST_ASSERT_TRUE(validateJobSequenceLine("G21", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G90", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G28", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G0 Z5 F120", state).accepted);
  TEST_ASSERT_TRUE(validateJobSequenceLine("G0 X10 Y10 F600", state).accepted);

  const auto result = validateJobSequenceLine("G0 X20 Y20 Z5 F120", state);
  TEST_ASSERT_FALSE(result.accepted);
  TEST_ASSERT_NOT_NULL(strstr(result.reason.c_str(), "simultaneous"));
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_comments_and_blank_lines_are_skipped);
  RUN_TEST(test_normal_plotter_commands_are_allowed);
  RUN_TEST(test_heater_extrusion_and_tool_commands_are_blocked);
  RUN_TEST(test_embedded_emergency_stop_is_blocked);
  RUN_TEST(test_unknown_and_coordinate_changing_commands_are_blocked);
  RUN_TEST(test_query_endpoint_only_allows_nonmoving_status_commands);
  RUN_TEST(test_sequence_rejects_motion_without_homing);
  RUN_TEST(test_sequence_allows_home_only_axis_diagnostics);
  RUN_TEST(test_sequence_accepts_guarded_generated_plot_with_diagonal_xy);
  RUN_TEST(test_sequence_requires_safe_pen_up_before_first_xy);
  RUN_TEST(test_sequence_requires_final_pen_up_after_plotting);
  RUN_TEST(test_sequence_requires_end_xy_rehome_after_plotting);
  RUN_TEST(test_sequence_rejects_z_homing_after_plotting_motion);
  RUN_TEST(test_sequence_rejects_out_of_bounds_and_excessive_feed);
  RUN_TEST(test_sequence_rejects_simultaneous_xy_and_z_motion_but_not_diagonal_xy);
  return UNITY_END();
}
