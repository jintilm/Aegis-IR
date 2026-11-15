add_llvm_pass_plugin(AegisPass
  Plugin.cpp
  AegisAuditPass.cpp
  AegisLintPass.cpp
  AegisPolicyPass.cpp
  AegisDecoysPass.cpp
  AegisControlFlowPass.cpp
  AegisVerifyPass.cpp
  Policy.cpp
  DecoyCorpus.cpp
  ControlFlow.cpp
)

target_compile_features(AegisPass PRIVATE cxx_std_17)
target_include_directories(AegisPass PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

option(AEGIS_BUILD_FUZZERS "Build standalone sanitizer fuzz targets" OFF)
if (AEGIS_BUILD_FUZZERS)
  add_executable(AegisPolicyFuzz
    ../tests/policy/fuzz_policy.cpp
    Policy.cpp
  )
  target_include_directories(AegisPolicyFuzz PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
  )
  target_compile_features(AegisPolicyFuzz PRIVATE cxx_std_17)
  target_compile_options(AegisPolicyFuzz PRIVATE
    -fsanitize=fuzzer,address,undefined
    -fno-sanitize-recover=all
    -fno-omit-frame-pointer
  )
  target_link_options(AegisPolicyFuzz PRIVATE
    -fsanitize=fuzzer,address,undefined
  )
  target_link_libraries(AegisPolicyFuzz PRIVATE LLVM)
endif()
