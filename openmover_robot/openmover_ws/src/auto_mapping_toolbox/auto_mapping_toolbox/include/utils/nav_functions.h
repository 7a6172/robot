#ifndef NAV_FUNCTIONS_H
#define NAV_FUNCTIONS_H

#include <ros/ros.h>
#include <random>
#include <map>
#include <unordered_map>
#include <nav_msgs/OccupancyGrid.h>
#include <visualization_msgs/MarkerArray.h>
#include <tf/tf.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <localization/localization_sources.h>
#include <common/common_state_code.h>
#include <openmover_msgs/nav_to_state.h>
#include <openmover_msgs/nav_to_request.h>
#include <openmover_msgs/cmd_vel_mode_request.h>
#include <navigation/navigation_state_code.h>
#include <angles/angles.h>

using namespace std;

class nav_functions
{
public:
    nav_functions() {};
    ~nav_functions() {};

    bool initialize();

    bool set_cmd_vel_mode(const bool &manual);
    bool nav_to(const float &x, const float &y, const float &yaw,
                const float &vxmax, const float &vyawmax,
                const bool &use_global_planner,
                const bool &ignore_obstacle,
                const bool &async);
    bool move(const float &dist, const float &angle,
              const float &vxmax, const float &vyawmax,
              const bool &ignore_obstacle,
              const bool &async);
    bool cancel();
    string get_nav_state();

private:
    unique_ptr<ros::NodeHandle> node_handle_;

    ros::ServiceClient nav_to_client_;
    ros::ServiceClient cmd_vel_mode_client_;

    ros::Subscriber nav_to_state_sub_;

    unique_ptr<tf2_ros::Buffer> tf_buffer_;
    unique_ptr<tf2_ros::TransformListener> tf_listener_;
    geometry_msgs::TransformStamped tf_map_to_base_link_;

    std::mutex mutex_state_;

    ros::CallbackQueue nav_to_state_queue_;

    openmover_msgs::nav_to_state nav_to_state_data_;
    bool nav_to_state_received_ = false;

    void nav_to_state_callback(const openmover_msgs::nav_to_state::ConstPtr &msg);
    void thread_loop();
};

#endif