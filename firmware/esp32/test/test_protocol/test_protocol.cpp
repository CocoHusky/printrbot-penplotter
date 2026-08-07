#include <cstring>
#include <unity.h>

#include "plotter_protocol.h"

using plotter::protocol::validateJobLine;
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

void test_query_endpoint_only_allows_nonmoving_status_commands() {
  TEST_ASSERT_TRUE(validateQuery("M115").accepted);
  TEST_ASSERT_TRUE(validateQuery("M119").accepted);
  TEST_ASSERT_TRUE(validateQuery("M114").accepted);
  TEST_ASSERT_TRUE(validateQuery("M503").accepted);
  TEST_ASSERT_FALSE(validateQuery("G28").accepted);
  TEST_ASSERT_FALSE(validateQuery("G0 X10").accepted);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_comments_and_blank_lines_are_skipped);
  RUN_TEST(test_normal_plotter_commands_are_allowed);
  RUN_TEST(test_heater_extrusion_and_tool_commands_are_blocked);
  RUN_TEST(test_embedded_emergency_stop_is_blocked);
  RUN_TEST(test_query_endpoint_only_allows_nonmoving_status_commands);
  return UNITY_END();
}
