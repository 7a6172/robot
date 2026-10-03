cmake_minimum_required(VERSION 3.8)
project(auto_mapping_toolbox)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra)
endif()
set(CMAKE_BUILD_TYPE Release)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(angles REQUIRED)
find_package(auto_mapping_toolbox_msgs REQUIRED)
find_package(openmover_msgs REQUIRED)
find_package(nav2_costmap_2d REQUIRED)
find_package(nav2_util REQUIRED)
find_package(OpenCV REQUIRED)
find_package(octomap REQUIRED)
find_package(PCL REQUIRED)
find_package(OpenMP REQUIRED)
find_package(osqp REQUIRED)

set(ROS_DEPS rclcpp geometry_msgs nav_msgs sensor_msgs visualization_msgs
  tf2 tf2_ros tf2_geometry_msgs angles auto_mapping_toolbox_msgs openmover_msgs
  nav2_costmap_2d nav2_util)

include_directories(include ${OpenCV_INCLUDE_DIRS} ${OCTOMAP_INCLUDE_DIRS} ${PCL_INCLUDE_DIRS})

# ------------------------------------------------------------------ libraries
add_library(math_utils src/utils/math_utils.cpp)
ament_target_dependencies(math_utils ${ROS_DEPS})
target_link_libraries(math_utils ${OpenCV_LIBRARIES} ${OCTOMAP_LIBRARIES} ${PCL_LIBRARIES} OpenMP::OpenMP_CXX)

add_library(nav_functions src/utils/nav_functions.cpp)
ament_target_dependencies(nav_functions ${ROS_DEPS})
target_link_libraries(nav_functions math_utils)

add_library(global_planner
  src/utils/global_planner/dijkstra.cpp
  src/utils/global_planner/quadratic_calculator.cpp
  src/utils/global_planner/grid_path.cpp
  src/utils/global_planner/gradient_path.cpp
  src/utils/global_planner/polyline_generation.cpp
  src/utils/global_planner/orientation_filter.cpp
  src/utils/global_planner/osqp_utils.cpp
  src/utils/global_planner/osqp_smoother.cpp
  src/utils/global_planner/backend_optimization.cpp
  src/utils/global_planner/planner.cpp
  src/utils/global_planner/planner_with_costmap.cpp)
ament_target_dependencies(global_planner ${ROS_DEPS})
target_link_libraries(global_planner
  osqp::osqp OpenMP::OpenMP_CXX math_utils ${PCL_LIBRARIES})

add_library(auto_mapping_utils
  src/utils/auto_mapping/collision_prediction.cpp
  src/utils/auto_mapping/global_exploration.cpp
  src/utils/auto_mapping/local_exploration.cpp
  src/utils/auto_mapping/tsp_optimization.cpp)
ament_target_dependencies(auto_mapping_utils ${ROS_DEPS})
target_link_libraries(auto_mapping_utils math_utils ${PCL_LIBRARIES})

# ---------------------------------------------------------------- executables
add_executable(auto_mapping_handler src/auto_mapping_handler.cpp)
ament_target_dependencies(auto_mapping_handler ${ROS_DEPS})
target_link_libraries(auto_mapping_handler
  math_utils nav_functions global_planner auto_mapping_utils)

# -------------------------------------------------------------------- install
install(TARGETS auto_mapping_handler DESTINATION lib/${PROJECT_NAME})
install(TARGETS math_utils nav_functions global_planner auto_mapping_utils DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config/ DESTINATION share/${PROJECT_NAME}/config)

ament_package()
