cmake_minimum_required(VERSION 3.0.2)

SET(CMAKE_BUILD_TYPE Release)

project(swjtumover_msgs)

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
)

set(CMAKE_CXX_FLAGS_RELEASE "-O3")

add_message_files(FILES
	motor_state.msg
)

add_service_files(FILES
)

add_action_files(DIRECTORY
	action
	FILES
)

generate_messages(DEPENDENCIES
	std_msgs
	geometry_msgs
	actionlib_msgs
	swjtumover_msgs
)

include_directories(
	include
	${catkin_INCLUDE_DIRS}
)

catkin_package(
	CATKIN_DEPENDS roscpp std_msgs message_runtime rospy costmap_2d tf2 tf2_ros tf2_sensor_msgs
	DEPENDS
	INCLUDE_DIRS
)