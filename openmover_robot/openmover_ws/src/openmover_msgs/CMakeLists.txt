# 2023-6-16 0.0.0.1A

cmake_minimum_required(VERSION 3.0.2)

SET(CMAKE_BUILD_TYPE Release)

project(openmover_msgs)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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
)

set(CMAKE_CXX_FLAGS_RELEASE "-O3")

add_message_files(FILES
	pose.msg
	twist.msg
	nav_to_state.msg
	flow_state.msg
	obstacle.msg
	bms_data.msg
	motor_state.msg
	nav_to_simple.msg
)

add_service_files(FILES
	mode/work_mode_request.srv
	localization/direct_request.srv
	navigation/nav_to_request.srv
	navigation/nav_to_simple_request.srv
	driver/stop_request.srv
	driver/playsound_request.srv
	driver/cmd_vel_mode_request.srv
	manager/flow_action.srv
	manager/flow_cmd.srv
	manager/self_test_report_request.srv
)

add_action_files(DIRECTORY
	action
	FILES
)

generate_messages(DEPENDENCIES
	std_msgs
	geometry_msgs
	actionlib_msgs
	openmover_msgs
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