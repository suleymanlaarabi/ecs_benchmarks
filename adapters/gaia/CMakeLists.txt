cmake_minimum_required(VERSION 3.20)
project(gaia_bench LANGUAGES CXX)

include(FetchContent)
FetchContent_Declare(
  gaia
  GIT_REPOSITORY https://github.com/richardbiely/gaia-ecs.git
  GIT_TAG v1.0.0
  GIT_SHALLOW FALSE
  # Populate the pinned source without evaluating Gaia's top-level project.
  SOURCE_SUBDIR _ecs_bench_no_cmake_project
)
FetchContent_MakeAvailable(gaia)

add_library(gaia_headers INTERFACE)
target_include_directories(gaia_headers INTERFACE "${gaia_SOURCE_DIR}/single_include")

add_executable(gaia-bench main.cpp)
target_link_libraries(gaia-bench PRIVATE gaia_headers)
target_compile_features(gaia-bench PRIVATE cxx_std_17)

if(MSVC)
  target_compile_options(gaia-bench PRIVATE /O2)
else()
  target_compile_options(gaia-bench PRIVATE -O3 -DNDEBUG)
endif()
