cmake_minimum_required(VERSION 3.8)
project(openmover)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra)
endif()
set(CMAKE_BUILD_TYPE Release)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(angles REQUIRED)
find_package(openmover_msgs REQUIRED)
find_package(relocalization_toolbox_msgs REQUIRED)
find_package(OpenCV REQUIRED)
find_package(octomap REQUIRED)
find_package(PCL REQUIRED)
find_package(OpenMP REQUIRED)
find_package(nav2_costmap_2d REQUIRED)
find_package(nav2_util REQUIRED)
find_package(tf2_eigen REQUIRED)
find_package(osqp REQUIRED)

set(ROS_DEPS rclcpp std_msgs geometry_msgs nav_msgs sensor_msgs tf2 tf2_ros
  tf2_geometry_msgs visualization_msgs angles openmover_msgs relocalization_toolbox_msgs
  nav2_costmap_2d nav2_util tf2_eigen)

include_directories(include ${OpenCV_INCLUDE_DIRS} ${OCTOMAP_INCLUDE_DIRS} ${PCL_INCLUDE_DIRS})

# ------------------------------------------------------------------ libraries
add_library(crc8_maxim src/driver/utils/crc8_maxim.cpp)

add_library(math_utils src/navigation/utils/math_utils.cpp)
ament_target_dependencies(math_utils ${ROS_DEPS})
target_link_libraries(math_utils ${OpenCV_LIBRARIES} ${OCTOMAP_LIBRARIES} ${PCL_LIBRARIES} OpenMP::OpenMP_CXX)

add_library(likelihood_field src/localization/utils/localization_confidence/likelihood_field.cpp)
ament_target_dependencies(likelihood_field ${ROS_DEPS})
target_link_libraries(likelihood_field math_utils)

# navigation utils libraries (Stage 4a)
add_library(controllers src/navigation/utils/controllers.cpp)
ament_target_dependencies(controllers ${ROS_DEPS})

add_library(mover src/navigation/utils/local_planner/mover.cpp)
ament_target_dependencies(mover ${ROS_DEPS})
target_link_libraries(mover controllers)

add_library(path_follower src/navigation/utils/local_planner/path_follower.cpp)
ament_target_dependencies(path_follower ${ROS_DEPS})
target_link_libraries(path_follower OpenMP::OpenMP_CXX controllers mover)

add_library(collision_checker src/navigation/utils/collision_checker/collision_checker.cpp)
ament_target_dependencies(collision_checker ${ROS_DEPS})
target_link_libraries(collision_checker math_utils ${PCL_LIBRARIES})

add_library(path_checker src/navigation/utils/path_checker/path_checker.cpp)
ament_target_dependencies(path_checker ${ROS_DEPS})
target_link_libraries(path_checker math_utils ${PCL_LIBRARIES})

add_library(global_planner_deps
  src/navigation/utils/global_planner/quadratic_calculator.cpp
  src/navigation/utils/global_planner/dijkstra.cpp
  src/navigation/utils/global_planner/grid_path.cpp
  src/navigation/utils/global_planner/gradient_path.cpp
  src/navigation/utils/global_planner/orientation_filter.cpp
  src/navigation/utils/global_planner/planner.cpp
  src/navigation/utils/global_planner/planner_with_costmap.cpp
  src/navigation/utils/global_planner/osqp_utils.cpp
  src/navigation/utils/global_planner/osqp_smoother.cpp
  src/navigation/utils/global_planner/backend_optimization.cpp
  src/navigation/utils/global_planner/polyline_generation.cpp)
ament_target_dependencies(global_planner_deps ${ROS_DEPS})
target_link_libraries(global_planner_deps
  osqp::osqp OpenMP::OpenMP_CXX math_utils ${PCL_LIBRARIES})

# ---------------------------------------------------------------- executables
add_executable(io_board_handler src/driver/io_board_handler.cpp)
ament_target_dependencies(io_board_handler ${ROS_DEPS})
target_link_libraries(io_board_handler crc8_maxim)

add_executable(motor_handler src/driver/motor_handler.cpp)
ament_target_dependencies(motor_handler ${ROS_DEPS})
target_link_libraries(motor_handler crc8_maxim)

add_executable(simulation_handler src/driver/simulation_handler.cpp)
ament_target_dependencies(simulation_handler ${ROS_DEPS})

add_executable(localization_handler src/localization/localization_handler.cpp)
ament_target_dependencies(localization_handler ${ROS_DEPS})
target_link_libraries(localization_handler math_utils)

add_executable(localization_confidence_handler src/localization/localization_confidence_handler.cpp)
ament_target_dependencies(localization_confidence_handler ${ROS_DEPS})
target_link_libraries(localization_confidence_handler likelihood_field)

add_executable(navigation_handler src/navigation/navigation/navigation_handler.cpp)
ament_target_dependencies(navigation_handler ${ROS_DEPS})
target_link_libraries(navigation_handler
  global_planner_deps path_follower collision_checker path_checker
  mover controllers math_utils)

add_executable(teleop_handler src/teleop/teleop_handler.cpp)
ament_target_dependencies(teleop_handler ${ROS_DEPS})

add_executable(obstacle_handler src/navigation/obstacle/obstacle_handler.cpp)
ament_target_dependencies(obstacle_handler ${ROS_DEPS})
target_link_libraries(obstacle_handler ${PCL_LIBRARIES})

# -------------------------------------------------------------------- install
install(TARGETS io_board_handler motor_handler simulation_handler
  localization_handler localization_confidence_handler navigation_handler
  teleop_handler obstacle_handler
  DESTINATION lib/${PROJECT_NAME})
install(TARGETS crc8_maxim math_utils likelihood_field
  controllers mover path_follower collision_checker path_checker global_planner_deps
  DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)

# Python layer (Stage 6): install executables and shared modules flat into
# lib/${PROJECT_NAME} so bare `import config/symbols/...` resolves via the
# script directory placed on sys.path[0] by the interpreter.
install(PROGRAMS
  scripts/driver/speaker_handler.py
  scripts/teleop/teleop_handler.py
  scripts/workload/workload.py
  scripts/server/func_mode_server_handler.py
  scripts/server/localization_mode_server_handler.py
  scripts/server/nav_area_server_handler.py
  scripts/server/reset_server_handler.py
  scripts/server/cartographer_server_handler.py
  scripts/server/cartographer_initialpose_adapter.py
  DESTINATION lib/${PROJECT_NAME})
install(FILES
  scripts/launch_manager.py
  scripts/hal/config.py
  scripts/hal/symbols.py
  scripts/hal/logger.py
  scripts/hal/utils.py
  scripts/hal/protocol.py
  scripts/hal/hal.py
  scripts/hal/cli.py
  DESTINATION lib/${PROJECT_NAME})

# Stage 8: install launch, default configs, maps, worlds, meshes and URDF resources.
install(DIRECTORY launch config_defaults maps_defaults worlds urdf meshes
    DESTINATION share/${PROJECT_NAME})

ament_package()
