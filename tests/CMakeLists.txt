add_test(
  NAME aegis-policy
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/policy/run.sh" "$<TARGET_FILE:AegisPass>"
)

add_test(
  NAME aegis-decoys
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/decoys/run.sh" "$<TARGET_FILE:AegisPass>"
)

add_test(
  NAME aegis-controlflow
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/controlflow/run.sh" "$<TARGET_FILE:AegisPass>"
)

add_test(
  NAME differential
  COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/differential/run.py"
          --plugin "$<TARGET_FILE:AegisPass>"
          --report "${CMAKE_BINARY_DIR}/differential-report.json"
)

add_test(
  NAME differential-representative
  COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/differential/run.py"
          --plugin "$<TARGET_FILE:AegisPass>"
          --fixture-dir "${CMAKE_CURRENT_SOURCE_DIR}/differential/suites/representative"
          --profiles "${CMAKE_CURRENT_SOURCE_DIR}/differential/suites/representative/profiles.json"
          --fuzz-cases 40
          --report "${CMAKE_BINARY_DIR}/representative-differential-report.json"
)

add_test(
  NAME protection-scorecard
  COMMAND python3 -m aegis_bench scorecard
          --differential "${CMAKE_BINARY_DIR}/differential-report.json"
          --budgets "${CMAKE_SOURCE_DIR}/experiments/protection-budgets.json"
          --out "${CMAKE_BINARY_DIR}/scorecard"
)
set_tests_properties(
  protection-scorecard
  PROPERTIES
    DEPENDS differential
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/tools/aegis-bench"
)

add_test(
  NAME protection-scorecard-representative
  COMMAND python3 -m aegis_bench scorecard
          --differential "${CMAKE_BINARY_DIR}/representative-differential-report.json"
          --budgets "${CMAKE_SOURCE_DIR}/experiments/protection-budgets-representative.json"
          --out "${CMAKE_BINARY_DIR}/scorecard-representative"
)
set_tests_properties(
  protection-scorecard-representative
  PROPERTIES
    DEPENDS differential-representative
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/tools/aegis-bench"
)

# Offline harness tests: deterministic adapters only, no model, no network.
add_test(
  NAME aegis-bench
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/bench/run.sh"
          "${CMAKE_CURRENT_SOURCE_DIR}/../tools/aegis-bench"
          "$<TARGET_FILE:AegisPass>"
)
