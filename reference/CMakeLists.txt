cmake_minimum_required(VERSION 3.20)
project(bencode-validator CXX)

# Disable libtorrent features we don't need
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(encryption OFF CACHE BOOL "" FORCE)
set(dht OFF CACHE BOOL "" FORCE)
set(build_tests OFF CACHE BOOL "" FORCE)
set(build_examples OFF CACHE BOOL "" FORCE)
set(build_tools OFF CACHE BOOL "" FORCE)
set(python-bindings OFF CACHE BOOL "" FORCE)

add_subdirectory(../../3rd/libtorrent libtorrent-build)

add_executable(validator validator.cpp)
target_link_libraries(validator PRIVATE torrent-rasterbar)
target_compile_features(validator PRIVATE cxx_std_17)
