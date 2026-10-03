cmake_minimum_required(VERSION 3.0.2)

SET(CMAKE_BUILD_TYPE Release)

project(openmover)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(osqp REQUIRED)

find_package(catkin REQUIRED COMPONENTS
	cartographer_ros_msgs
	roslaunch
	geometry_msgs
	nav_msgs
	roscpp
	rospy
	sensor_msgs
	costmap_2d
	tf
	urdf
	message_generation
	std_msgs
	genmsg
	actionlib_msgs
	actionlib
	pcl_ros
	laser_geometry
	tf2
	tf2_ros
	tf2_sensor_msgs
	openmover_msgs
	serial
	cv_bridge
	relocalization_toolbox_msgs
	auto_mapping_toolbox_msgs
)

find_package(Eigen3 REQUIRED)
find_package(PCL REQUIRED)
find_package(OpenCV REQUIRED)
find_package(OpenMP REQUIRED)
add_definitions(${PCL_DEFINITIONS})

set(CMAKE_CXX_FLAGS_RELEASE "-O3")

include_directories(
	include
	${PCL_INCLUDE_DIRS}
	${EIGEN3_INCLUDE_DIR}
	${catkin_INCLUDE_DIRS}
)

catkin_package(
	CATKIN_DEPENDS roscpp std_msgs message_runtime rospy costmap_2d tf2 tf2_ros tf2_sensor_msgs relocalization_toolbox_msgs
	DEPENDS EIGEN3 PCL OpenCV
	INCLUDE_DIRS
)

# driver
add_library(crc8_maxim
	src/driver/utils/crc8_maxim.cpp
)

target_link_libraries(crc8_maxim
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_executable(io_board_handler
	src/driver/io_board_handler.cpp)

target_link_libraries(io_board_handler
	crc8_maxim
	${catkin_LIBRARIES}
	${Boost_LIBRARIES}
)

add_executable(motor_handler
	src/driver/motor_handler.cpp)

target_link_libraries(motor_handler
	crc8_maxim
	${catkin_LIBRARIES}
	${Boost_LIBRARIES}
)

add_executable(simulation_handler
	src/driver/simulation_handler.cpp)

target_link_libraries(simulation_handler
	${catkin_LIBRARIES}
	${Boost_LIBRARIES}
)

# teleop
add_executable(teleop_handler
	src/teleop/teleop_handler.cpp
)

target_link_libraries(teleop_handler
	${catkin_LIBRARIES}
)

# localization
add_library(math_utils
	src/navigation/utils/math_utils.cpp
)

target_link_libraries(math_utils
	PRIVATE OpenMP::OpenMP_CXX
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_executable(localization_handler
	src/localization/localization_handler.cpp
)

target_link_libraries(localization_handler
	${catkin_LIBRARIES}
)

add_library(likelihood_field
	src/localization/utils/localization_confidence/likelihood_field.cpp
)

target_link_libraries(likelihood_field
	PRIVATE OpenMP::OpenMP_CXX
	math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_executable(localization_confidence_handler
	src/localization/localization_confidence_handler.cpp
)

target_link_libraries(localization_confidence_handler
	math_utils
	likelihood_field
	${catkin_LIBRARIES}
)

# navigation
add_library(controllers
	src/navigation/utils/controllers.cpp
)

add_library(mover
	src/navigation/utils/local_planner/mover.cpp
)

target_link_libraries(mover
	controllers
	${catkin_LIBRARIES}
)

add_library(path_follower
	src/navigation/utils/local_planner/path_follower.cpp
)

target_link_libraries(path_follower
	OpenMP::OpenMP_CXX
	controllers
	mover
	${catkin_LIBRARIES}
)

add_library(collision_checker
	src/navigation/utils/collision_checker/collision_checker.cpp
)

target_link_libraries(collision_checker
	math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_library(path_checker
	src/navigation/utils/path_checker/path_checker.cpp
)

target_link_libraries(path_checker
	math_utils
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

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
	src/navigation/utils/global_planner/polyline_generation.cpp
)

target_link_libraries(global_planner_deps
	PRIVATE osqp::osqp
	PRIVATE OpenMP::OpenMP_CXX
	math_utils
	${PCL_LIBRARIES}
)

add_executable(global_planner_handler
	src/navigation/global_planner/global_planner_handler.cpp
)

target_link_libraries(global_planner_handler
	global_planner_deps
	${catkin_LIBRARIES}
)

add_executable(navigation_handler
	src/navigation/navigation/navigation_handler.cpp
)

target_link_libraries(navigation_handler
	path_follower
	controllers
	mover
	math_utils
	path_checker
	collision_checker
	global_planner_deps
	${catkin_LIBRARIES}
)

add_executable(obstacle_handler
	src/navigation/obstacle/obstacle_handler.cpp
)

target_link_libraries(obstacle_handler
	${catkin_LIBRARIES}
)
