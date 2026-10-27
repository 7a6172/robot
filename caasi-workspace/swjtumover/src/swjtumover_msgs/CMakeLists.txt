cmake_minimum_required(VERSION 3.16)
project(swjtumover_msgs)

# ROS 1 defined one message (motor_state.msg) in a package that pulled in half of ROS 1 as a
# build dependency. ROS 2 needs exactly the interface and nothing else: the driver board's
# per-channel telemetry plus its fault flags.
find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/MotorState.msg"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
