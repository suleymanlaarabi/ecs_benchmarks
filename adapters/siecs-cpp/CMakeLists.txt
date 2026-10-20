cmake_minimum_required(VERSION 3.20)
project(siecs_cpp_bench LANGUAGES C CXX)

set(SIECS_ROOT "" CACHE PATH "Path to the local Siecs repository")
set(SIECS_COMMIT "3ec502180e03c8ef7b8269541f553402ee617999")
# SIECS_DISTR_ROOT (environment) names a tree holding a pre-generated
# distr/siecs.{c,h}. It skips the pinned commit check for local development
# and A/B builds; it is read on every configure so it never sticks in the cache.
set(SIECS_DISTR_ROOT "$ENV{SIECS_DISTR_ROOT}")
set(SIECS_BENCH_VERSION "3ec5021")
if(NOT "$ENV{SIECS_BENCH_VERSION}" STREQUAL "")
  set(SIECS_BENCH_VERSION "$ENV{SIECS_BENCH_VERSION}")
endif()
find_package(Git REQUIRED)
execute_process(
  COMMAND "${GIT_EXECUTABLE}" -C "${SIECS_ROOT}" rev-parse HEAD
  OUTPUT_VARIABLE SIECS_LOCAL_COMMIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
execute_process(
  COMMAND "${GIT_EXECUTABLE}" -C "${SIECS_ROOT}" status --porcelain
  OUTPUT_VARIABLE SIECS_LOCAL_CHANGES
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
if(NOT SIECS_DISTR_ROOT STREQUAL "")
  set(SIECS_ROOT "${SIECS_DISTR_ROOT}")
elseif(NOT SIECS_LOCAL_COMMIT STREQUAL SIECS_COMMIT OR NOT SIECS_LOCAL_CHANGES STREQUAL "")
  set(SIECS_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../build/siecs/_deps/siecs-src")
endif()
if(NOT IS_DIRECTORY "${SIECS_ROOT}/include")
  message(FATAL_ERROR "SIECS_ROOT must point to a Siecs checkout")
endif()

set(SIECS_SOURCE "${SIECS_ROOT}/distr/siecs.c")
set(SIECS_INCLUDE "${SIECS_ROOT}/distr")
if(NOT EXISTS "${SIECS_SOURCE}" OR NOT EXISTS "${SIECS_ROOT}/distr/siecs.h")
  message(FATAL_ERROR "Siecs amalgamation is missing from ${SIECS_ROOT}/distr")
endif()

add_library(siecs_core STATIC "${SIECS_SOURCE}")
target_compile_features(siecs_core PUBLIC c_std_23)
target_include_directories(siecs_core PUBLIC "${SIECS_INCLUDE}")
if(NOT WIN32)
  target_link_libraries(siecs_core PUBLIC pthread ${CMAKE_DL_LIBS})
endif()

add_executable(siecs-cpp-bench main.cpp)
target_compile_features(siecs-cpp-bench PRIVATE cxx_std_20)
target_link_libraries(siecs-cpp-bench PRIVATE siecs_core)
target_compile_definitions(siecs-cpp-bench PRIVATE SIECS_BENCH_VERSION="${SIECS_BENCH_VERSION}")

if(MSVC)
  target_compile_options(siecs-cpp-bench PRIVATE /O2)
else()
  target_compile_options(siecs-cpp-bench PRIVATE -O3 -DNDEBUG)
endif()
