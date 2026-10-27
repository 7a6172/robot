cmake_minimum_required(VERSION 3.16)
project(swjtumover_bringup CXX)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(swjtumover_msgs REQUIRED)

# motor_node: the robot's only actuator path. Its protocol, odometry maths and the
# motor_safety Guard come from the ROS 1 package unchanged.
# crc8_maxim is shared by the motor and screen protocols; it is plain C++ and is compiled
# into each consumer rather than built as a library.
add_library(crc8_maxim STATIC src/utils/crc8_maxim.cpp)
target_include_directories(crc8_maxim PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")

add_executable(motor_node src/motor_node.cpp)
target_link_libraries(motor_node crc8_maxim)
target_include_directories(motor_node PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
ament_target_dependencies(motor_node
  rclcpp geometry_msgs nav_msgs tf2 tf2_ros tf2_geometry_msgs swjtumover_msgs)

# screen_node: writes text frames to the display board.
add_executable(screen_node src/screen_node.cpp)
ament_target_dependencies(screen_node rclcpp std_msgs)

# Operator and task nodes, installed as programs so `ros2 run` and the launch files work.
install(PROGRAMS
  scripts/teleop_node.py
  scripts/obstacle_rplidar.py
  scripts/omove_following_feng.py
  scripts/line_then_home.py
  DESTINATION lib/${PROJECT_NAME})
install(TARGETS motor_node screen_node DESTINATION lib/${PROJECT_NAME})

# Launch, configuration, model and the ROS 1 parity data that the tests compare against.
install(DIRECTORY launch config urdf param rviz
        DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(
    migration_parity test/test_migration_parity.py
    APPEND_ENV PYTHONPATH="${CMAKE_CURRENT_SOURCE_DIR}")
  ament_add_pytest_test(
    launch_selection test/test_launch_selection.py
    APPEND_ENV PYTHONPATH="${CMAKE_CURRENT_SOURCE_DIR}")
  ament_add_pytest_test(
    task_migration test/test_task_migration.py
    APPEND_ENV PYTHONPATH="${CMAKE_CURRENT_SOURCE_DIR}")
endif()

ament_package()
