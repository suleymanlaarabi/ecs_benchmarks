cmake_minimum_required(VERSION 3.20)
project(flecs_bench LANGUAGES C)

include(FetchContent)
FetchContent_Declare(
  flecs
  GIT_REPOSITORY https://github.com/SanderMertens/flecs.git
  GIT_TAG v4.1.5
  GIT_SHALLOW TRUE
  # Populate the sources without using upstream's glob of every addon file.
  SOURCE_SUBDIR _ecs_bench_no_cmake_project
)
FetchContent_MakeAvailable(flecs)

# Flecs enables every feature addon unless FLECS_CUSTOM_BUILD is defined.
# Benchmarks only need the core ECS plus the default platform/allocator backend.
# PUBLIC keeps the library and consumer header configuration identical.
file(
  GLOB_RECURSE FLECS_CORE_SOURCES
  CONFIGURE_DEPENDS
  "${flecs_SOURCE_DIR}/src/*.c"
)
list(FILTER FLECS_CORE_SOURCES EXCLUDE REGEX "/src/addons/")
list(
  APPEND FLECS_CORE_SOURCES
  # Core error reporting and query validation use these support units even
  # when the corresponding feature macros are disabled.
  "${flecs_SOURCE_DIR}/src/addons/log.c"
  "${flecs_SOURCE_DIR}/src/addons/parser/tokenizer.c"
  "${flecs_SOURCE_DIR}/src/addons/os_api_impl/os_api_impl.c"
)

add_library(flecs_core STATIC ${FLECS_CORE_SOURCES})
target_compile_features(flecs_core PUBLIC c_std_99)
target_include_directories(flecs_core PUBLIC "${flecs_SOURCE_DIR}/include")
target_compile_definitions(
  flecs_core
  PUBLIC
  flecs_STATIC
  FLECS_CUSTOM_BUILD
  FLECS_OS_API_IMPL
)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  target_link_libraries(flecs_core PUBLIC pthread)
elseif(WIN32)
  target_link_libraries(flecs_core PUBLIC wsock32 ws2_32 dbghelp)
endif()

add_executable(flecs-bench main.c)
target_compile_features(flecs-bench PRIVATE c_std_11)
target_link_libraries(flecs-bench PRIVATE flecs_core)

if(MSVC)
  target_compile_options(flecs-bench PRIVATE /O2)
else()
  target_compile_definitions(flecs-bench PRIVATE _POSIX_C_SOURCE=200809L)
  target_compile_options(flecs-bench PRIVATE -O3 -DNDEBUG)
endif()
