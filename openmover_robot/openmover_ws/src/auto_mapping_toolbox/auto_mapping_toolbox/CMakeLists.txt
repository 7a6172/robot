cmake_minimum_required(VERSION 3.0.2)
project(auto_mapping_toolbox)

set(CMAKE_BUILD_TYPE Release)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(osqp REQUIRED)

find_package(catkin REQUIRED COMPONENTS
  roscpp
  rospy
  std_msgs
  geometry_msgs
  nav_msgs
  sensor_msgs
  tf
  tf2
  tf2_ros
  tf2_sensor_msgs
  message_generation
  genmsg
  actionlib
  actionlib_msgs
  pcl_ros
  cv_bridge
  auto_mapping_toolbox_msgs
  openmover_msgs
)

find_package(Eigen3 REQUIRED)
find_package(PCL REQUIRED)
find_package(OpenCV REQUIRED)
find_package(OpenMP REQUIRED)

add_definitions(${PCL_DEFINITIONS})

include_directories(
  include
  ${catkin_INCLUDE_DIRS}
  ${PCL_INCLUDE_DIRS}
  ${EIGEN3_INCLUDE_DIR}
  ${YAML_CPP_INCLUDE_DIRS}
)

catkin_package(
  CATKIN_DEPENDS
    roscpp
    rospy
    std_msgs
    tf2
    tf2_ros
    tf2_sensor_msgs
    message_runtime
    auto_mapping_toolbox_msgs
  DEPENDS
    EIGEN3
    PCL
    OpenCV
)

add_library(auto_mapping_math_utils
	src/utils/math_utils.cpp
)

add_library(auto_mapping_global_planner_deps
	src/utils/global_planner/quadratic_calculator.cpp
	src/utils/global_planner/dijkstra.cpp
	src/utils/global_planner/grid_path.cpp
	src/utils/global_planner/gradient_path.cpp
	src/utils/global_planner/orientation_filter.cpp
	src/utils/global_planner/planner.cpp
	src/utils/global_planner/planner_with_costmap.cpp
	src/utils/global_planner/osqp_utils.cpp
	src/utils/global_planner/osqp_smoother.cpp
	src/utils/global_planner/backend_optimization.cpp
	src/utils/global_planner/polyline_generation.cpp
)

target_link_libraries(auto_mapping_global_planner_deps
	PRIVATE osqp::osqp
	PRIVATE OpenMP::OpenMP_CXX
	auto_mapping_math_utils
	${PCL_LIBRARIES}
)

add_library(global_exploration
	src/utils/auto_mapping/global_exploration.cpp
)

target_link_libraries(global_exploration
	auto_mapping_math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_library(local_exploration
	src/utils/auto_mapping/local_exploration.cpp
)

target_link_libraries(local_exploration
	auto_mapping_math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_library(tsp_optimization
	src/utils/auto_mapping/tsp_optimization.cpp
)

target_link_libraries(tsp_optimization
	auto_mapping_math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_library(collision_prediction
	src/utils/auto_mapping/collision_prediction.cpp
)

target_link_libraries(collision_prediction
	auto_mapping_math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_library(nav_functions
	src/utils/nav_functions.cpp
)

target_link_libraries(nav_functions
	auto_mapping_math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_executable(auto_mapping_handler
	src/auto_mapping_handler.cpp
)

target_link_libraries(auto_mapping_handler
	global_exploration
	local_exploration
	tsp_optimization
	nav_functions
	collision_prediction
	auto_mapping_math_utils
  	auto_mapping_global_planner_deps
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)