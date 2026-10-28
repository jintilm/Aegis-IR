add_llvm_pass_plugin(AegisPass AegisAuditPass.cpp)

target_compile_features(AegisPass PRIVATE cxx_std_17)
target_include_directories(AegisPass PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../include)