cmake_minimum_required(VERSION 3.20)
project(siecs_bench LANGUAGES C)

set(SIECS_ROOT "" CACHE PATH "Path to the local Siecs repository")
if(NOT IS_DIRECTORY "${SIECS_ROOT}/include")
  message(FATAL_ERROR "SIECS_ROOT must point to a Siecs checkout")
endif()

execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env BAKE_CONFIG=release bake env
  OUTPUT_VARIABLE BAKE_ENV
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY
)
string(REGEX MATCH "BAKE_HOME=([^\n\r]+)" _bake_home_match "${BAKE_ENV}")
set(BAKE_HOME "${CMAKE_MATCH_1}")
string(REGEX MATCH "BAKE_TARGET=([^\n\r]+)" _bake_target_match "${BAKE_ENV}")
set(BAKE_TARGET "${CMAKE_MATCH_1}")

find_library(
  SIECS_LIBRARY
  NAMES siecs
  PATHS "${BAKE_TARGET}/lib"
  NO_DEFAULT_PATH
  REQUIRED
)

add_executable(siecs-bench main.c)
target_compile_features(siecs-bench PRIVATE c_std_23)
target_include_directories(
  siecs-bench
  PRIVATE
  "${SIECS_ROOT}/include"
  "${BAKE_HOME}/include"
)
target_link_libraries(siecs-bench PRIVATE "${SIECS_LIBRARY}")
set_target_properties(siecs-bench PROPERTIES BUILD_RPATH "${BAKE_TARGET}/lib")

if(MSVC)
  target_compile_options(siecs-bench PRIVATE /O2)
else()
  target_compile_options(siecs-bench PRIVATE -O3 -DNDEBUG)
  if(NOT APPLE)
    target_link_libraries(siecs-bench PRIVATE pthread)
    # DT_RPATH is inherited while resolving libsiecs' shared dependencies.
    target_link_options(siecs-bench PRIVATE "-Wl,--disable-new-dtags")
  endif()
endif()
