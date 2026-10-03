cmake_minimum_required(VERSION 3.8)
project(warehouse_simulation)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)

# 键盘遥控节点（ROS 1 key_control.cpp 的移植）
add_executable(key_control src/key_control.cpp)
ament_target_dependencies(key_control rclcpp geometry_msgs)
install(TARGETS key_control
  DESTINATION lib/${PROJECT_NAME})

# Python 可执行脚本（平铺安装到 lib/${PROJECT_NAME}）
install(PROGRAMS scripts/trajectory_server.py scripts/cmd_vel_watchdog.py
  DESTINATION lib/${PROJECT_NAME})

# 资源目录：world / urdf / meshes / models / config / rviz / launch / scripts
install(DIRECTORY launch config meshes models rviz scripts urdf worlds
  DESTINATION share/${PROJECT_NAME})

# 让 gz 能把 share/${PROJECT_NAME} 识别为模型目录（解析 model:// URI）
install(FILES model.config
  DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_config_yaml test/test_config_yaml.py)
  ament_add_pytest_test(test_trajectory_server test/test_trajectory_server.py
    TIMEOUT 60)
endif()

ament_package()
