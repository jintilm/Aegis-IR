add_test(
  NAME aegis-policy
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/policy/run.sh" "$<TARGET_FILE:AegisPass>"
)

add_test(
  NAME aegis-decoys
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/decoys/run.sh" "$<TARGET_FILE:AegisPass>"
)

add_test(
  NAME differential
  COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/differential/run.py"
          --plugin "$<TARGET_FILE:AegisPass>"
          --report "${CMAKE_BINARY_DIR}/differential-report.json"
)