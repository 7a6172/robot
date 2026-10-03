cmake_minimum_required(VERSION 3.8)
project(openmover_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/BmsData.msg"
  "msg/FlowState.msg"
  "msg/MotorState.msg"
  "msg/NavToSimple.msg"
  "msg/NavToState.msg"
  "msg/Obstacle.msg"
  "msg/Pose.msg"
  "msg/Twist.msg"
  "srv/CmdVelModeRequest.srv"
  "srv/DirectRequest.srv"
  "srv/FlowAction.srv"
  "srv/FlowCmd.srv"
  "srv/NavToRequest.srv"
  "srv/NavToSimpleRequest.srv"
  "srv/PlaysoundRequest.srv"
  "srv/SelfTestReportRequest.srv"
  "srv/StopRequest.srv"
  "srv/WorkModeRequest.srv"
  DEPENDENCIES std_msgs geometry_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_msgs_import test/test_msgs_import.py)
endif()

ament_package()
