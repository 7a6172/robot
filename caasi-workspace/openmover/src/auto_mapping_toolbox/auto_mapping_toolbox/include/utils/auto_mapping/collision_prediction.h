#ifndef COLLISION_PREDICTION_H
#define COLLISION_PREDICTION_H

#include <rclcpp/rclcpp.hpp>
#include <random>
#include <map>
#include <unordered_map>
#include <utils/math_utils.h>
#include <utils/auto_mapping/rrt_common.h>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>

using namespace std;

namespace collision_prediction
{
    class collision_predictor
    {
    public:
        collision_predictor(const bool &use_external_dist_table = false, const int &free_threshold = 30, const int &occupied_threshold = 55);
        ~collision_predictor()
        {
            stop_flag_ = true;

            if (map_thread_.joinable())
            {
                map_thread_.join();
            }
        };

        void initialize(rclcpp::Node::SharedPtr node);
        bool check(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const int &step,
                   const float &min_dist_to_obs, const nav_msgs::msg::OccupancyGrid &grid,
                   const vector<float> &obs_dist_table,
                   const int &free_threshold, const int &occupied_threshold);
        bool check(const geometry_msgs::msg::PoseStamped &p0, const geometry_msgs::msg::PoseStamped &p1, const int &step,
                   const float &min_dist_to_obs, const nav_msgs::msg::OccupancyGrid &grid,
                   const vector<float> &obs_dist_table,
                   const int &free_threshold, const int &occupied_threshold);
        bool check(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const int &step,
                   const float &min_dist_to_obs);
        bool check(const geometry_msgs::msg::PoseStamped &p0, const geometry_msgs::msg::PoseStamped &p1, const int &step,
                   const float &min_dist_to_obs);

    private:
        rclcpp::Node::SharedPtr node_;

        unique_ptr<tf2_ros::Buffer> tf_buffer_;
        unique_ptr<tf2_ros::TransformListener> tf_listener_;

        rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub_;
        rclcpp::CallbackGroup::SharedPtr map_callback_group_;
        rclcpp::executors::SingleThreadedExecutor::UniquePtr map_executor_;
        thread map_thread_;
        bool stop_flag_ = false;

        geometry_msgs::msg::TransformStamped tf_map_to_base_link_;
        geometry_msgs::msg::TransformStamped tf_map_to_lidar_link_;

        nav_msgs::msg::OccupancyGrid map_data_;
        vector<float> min_dist_to_obs_table_;
        sensor_msgs::msg::LaserScan scan_data_;

        std::mutex mutex_data_;

        bool use_external_dist_table_;
        int free_threshold_, occupied_threshold_;
        float min_dist_to_obs_ = 0.25;

        void map_callback(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr &msg);
        void thread_loop();
    };
}

#endif