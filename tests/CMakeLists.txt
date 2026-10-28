add_test(
  NAME aegis-policy
  COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/policy/run.sh" "$<TARGET_FILE:AegisPass>"
)