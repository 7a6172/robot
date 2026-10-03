#ifndef NAV_FUNCTIONS_H
#define NAV_FUNCTIONS_H

#include <rclcpp/rclcpp.hpp>
#include <random>
#include <map>
#include <thread>
#include <unordered_map>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <localization/localization_sources.h>
#include <common/common_state_code.h>
#include <openmover_msgs/msg/nav_to_state.hpp>
#include <openmover_msgs/srv/nav_to_request.hpp>
#include <openmover_msgs/srv/cmd_vel_mode_request.hpp>
#include <navigation/navigation_state_code.h>
#include <angles/angles/angles.h>

using namespace std;

class nav_functions
{
public:
    nav_functions() {};
    ~nav_functions()
    {
        if (nav_to_state_thread_ != nullptr && nav_to_state_thread_->joinable())
        {
            nav_to_state_thread_->join();
        }
    };

    bool initialize(rclcpp::Node::SharedPtr node);

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
    rclcpp::Node::SharedPtr node_;

    rclcpp::Subscription<openmover_msgs::msg::NavToState>::SharedPtr nav_to_state_sub_;

    rclcpp::CallbackGroup::SharedPtr nav_to_state_callback_group_;
    rclcpp::executors::SingleThreadedExecutor::UniquePtr nav_to_state_executor_;
    unique_ptr<thread> nav_to_state_thread_;

    unique_ptr<tf2_ros::Buffer> tf_buffer_;
    unique_ptr<tf2_ros::TransformListener> tf_listener_;
    geometry_msgs::msg::TransformStamped tf_map_to_base_link_;

    std::mutex mutex_state_;

    openmover_msgs::msg::NavToState nav_to_state_data_;
    bool nav_to_state_received_ = false;

    void nav_to_state_callback(const openmover_msgs::msg::NavToState::ConstSharedPtr &msg);
    void thread_loop();
};

#endif