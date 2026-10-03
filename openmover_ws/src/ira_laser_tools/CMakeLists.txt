cmake_minimum_required(VERSION 3.8)
project(ira_laser_tools)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(laser_geometry REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(laserscan_multi_merger src/laserscan_multi_merger.cpp)
ament_target_dependencies(laserscan_multi_merger
  rclcpp sensor_msgs laser_geometry tf2 tf2_ros)

install(TARGETS laserscan_multi_merger
  DESTINATION lib/${PROJECT_NAME})

ament_package()
