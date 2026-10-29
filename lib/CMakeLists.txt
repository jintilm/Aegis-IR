add_llvm_pass_plugin(AegisPass
  Plugin.cpp
  AegisAuditPass.cpp
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