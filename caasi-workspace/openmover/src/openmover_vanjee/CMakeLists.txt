cmake_minimum_required(VERSION 3.16)
project(openmover_vanjee CXX)

# The vendor driver is ROS-independent and header-only for our purposes: including its
# headers is enough, so there is no vendor library to build, no vanjee_lidar_msg
# dependency, and no patch to the vendor CMake options. The source lives under
# external/ (an unmodified copy) rather than inside caasi's own tree.
set(VANJEE_DRIVER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../external/vanjee_driver")

if(NOT EXISTS "${VANJEE_DRIVER_DIR}/CMakeLists.txt")
  message(FATAL_ERROR
    "Vanjee driver source not found at ${VANJEE_DRIVER_DIR}. "
    "It is an external dependency; see the package README.")
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(Eigen3 QUIET)

add_executable(vanjee_scan_node src/vanjee_scan_node.cpp)
target_include_directories(vanjee_scan_node PRIVATE
  "${VANJEE_DRIVER_DIR}/src")
# Matches the vendor's default (DISABLE_PCAP_PARSE=ON). Without it the driver's pcap
# input path is compiled in and the link needs libpcap, which is not a dependency we want
# for an online-lidar node.
target_compile_definitions(vanjee_scan_node PRIVATE DISABLE_PCAP_PARSE)

if(TARGET Eigen3::Eigen)
  target_link_libraries(vanjee_scan_node Eigen3::Eigen)
endif()

ament_target_dependencies(vanjee_scan_node rclcpp sensor_msgs)

install(TARGETS vanjee_scan_node DESTINATION lib/${PROJECT_NAME})
ament_package()
