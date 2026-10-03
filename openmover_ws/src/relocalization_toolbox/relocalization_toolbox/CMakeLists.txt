cmake_minimum_required(VERSION 3.8)
project(relocalization_toolbox)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra)
endif()
# 与 ROS 1 CMakeLists 一致的优化选项（重定位打分/采样为计算热点）
add_compile_options(-O3 -flto -ffast-math -funroll-loops)
add_link_options(-flto)
set(CMAKE_BUILD_TYPE Release)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(tf2_eigen REQUIRED)
find_package(angles REQUIRED)
find_package(relocalization_toolbox_msgs REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(OpenCV REQUIRED)
find_package(octomap REQUIRED)
find_package(PCL REQUIRED)
find_package(OpenMP REQUIRED)
find_package(yaml-cpp REQUIRED)

set(ROS_DEPS rclcpp std_msgs std_srvs geometry_msgs nav_msgs sensor_msgs
  visualization_msgs tf2 tf2_ros tf2_geometry_msgs tf2_eigen angles relocalization_toolbox_msgs
  pcl_conversions)

include_directories(include ${OpenCV_INCLUDE_DIRS} ${OCTOMAP_INCLUDE_DIRS} ${PCL_INCLUDE_DIRS})

# ------------------------------------------------------------------ libraries
add_library(relocalization_2d_utils
  src/utils/math_utils.cpp
  src/utils/2d/gicp_2d.cpp
  src/utils/2d/likelihood_field_2d.cpp
  src/utils/2d/map_io_2d.cpp
  src/utils/2d/relocalization_2d.cpp
  src/utils/2d/sampling_2d.cpp
  src/utils/2d/sector_query_2d.cpp
  src/utils/2d/submap_set_2d.cpp)
ament_target_dependencies(relocalization_2d_utils ${ROS_DEPS})
target_link_libraries(relocalization_2d_utils
  ${OpenCV_LIBRARIES} ${OCTOMAP_LIBRARIES} ${PCL_LIBRARIES}
  OpenMP::OpenMP_CXX yaml-cpp)

# ---------------------------------------------------------------- executables
add_executable(relocalization_2d_handler src/relocalization_2d_handler.cpp)
ament_target_dependencies(relocalization_2d_handler ${ROS_DEPS})
target_link_libraries(relocalization_2d_handler relocalization_2d_utils)

# -------------------------------------------------------------------- install
install(TARGETS relocalization_2d_handler DESTINATION lib/${PROJECT_NAME})
install(TARGETS relocalization_2d_utils DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config/ DESTINATION share/${PROJECT_NAME}/config)

ament_package()
