cmake_minimum_required(VERSION 3.0.2)

SET(CMAKE_BUILD_TYPE Release)

project(swjtumover_bringup)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(catkin REQUIRED COMPONENTS
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
	swjtumover_msgs
	cv_bridge
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
	CATKIN_DEPENDS roscpp std_msgs message_runtime rospy costmap_2d tf2 tf2_ros tf2_sensor_msgs
	DEPENDS EIGEN3 PCL OpenCV
	INCLUDE_DIRS
)

add_library(crc8_maxim
	src/utils/crc8_maxim.cpp
)

target_link_libraries(crc8_maxim
	${catkin_LIBRARIES}
	${PCL_LIBRARIES}
)

add_executable(motor_node
	src/motor_node.cpp)

target_link_libraries(motor_node
	crc8_maxim
	${catkin_LIBRARIES}
	${Boost_LIBRARIES}
)

add_executable(screen_node
	src/screen_node.cpp)

target_link_libraries(screen_node
	${catkin_LIBRARIES}
	${Boost_LIBRARIES}
)