cmake_minimum_required(VERSION 3.8)
project(bluesea2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

add_compile_options(-Wno-unused-result -Wno-unused-variable -Wno-narrowing -Wno-sign-compare)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/Control.srv"
  "srv/DefenceZone.srv"
)

add_executable(bluesea2_node
  src/bluesea_node.cpp
  src/parser.cpp
  src/data_process.cpp
  src/algorithmAPI.cpp
  src/tcp_reader.cpp
  src/udp_reader.cpp
  src/uart_reader.cpp
  src/uart.c)
set_source_files_properties(src/uart.c PROPERTIES LANGUAGE C)
target_include_directories(bluesea2_node PRIVATE src)
ament_target_dependencies(bluesea2_node rclcpp sensor_msgs std_msgs)
rosidl_get_typesupport_target(cpp_typesupport_target ${PROJECT_NAME} rosidl_typesupport_cpp)
target_link_libraries(bluesea2_node "${cpp_typesupport_target}")

add_executable(bluesea2_node_client src/bluesea_node_client.cpp)
ament_target_dependencies(bluesea2_node_client rclcpp)
target_link_libraries(bluesea2_node_client "${cpp_typesupport_target}")

install(TARGETS bluesea2_node bluesea2_node_client
  DESTINATION lib/${PROJECT_NAME})
install(FILES src/LHLiDAR.rules
  DESTINATION share/${PROJECT_NAME})

ament_package()
