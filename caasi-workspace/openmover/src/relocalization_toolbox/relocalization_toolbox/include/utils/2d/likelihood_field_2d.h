/**
 * @author
 *   ZHANG Muhua
 * @affiliation
 *   Southwest Jiaotong University
 * @license
 *   GPL-3.0 License
 *
 * ROS 2 Jazzy port by zar (zar@my.swjtu.edu.cn)
 */

#ifndef LIKELIHOOD_FIELD_2D_H
#define LIKELIHOOD_FIELD_2D_H

#include <rclcpp/rclcpp.hpp>
#include <algorithm>
#include <random>
#include <map>
#include <unordered_map>
#include <utils/math_utils.h>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2/utils.hpp>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <geometry_msgs/msg/point_stamped.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>

using namespace std;

namespace likelihood_field_2d
{
    class likelihood_field_2d
    {
    public:
        likelihood_field_2d(rclcpp::Node::SharedPtr node, const float &sigma_hit = 0.2f, const float &z_hit = 1.0f, const float &z_rand = 0.0f, const int &map_occupied_threshold = 50);
        ~likelihood_field_2d() {};

        tuple<float, float, float> get_likelihood_field_score(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                              const sensor_msgs::msg::LaserScan &scan,
                                                              const nav_msgs::msg::OccupancyGrid &map,
                                                              const vector<float> &obs_dist_table,
                                                              const int &lidar_sampling_step,
                                                              const bool &enable_visualization = false);
        tuple<float, float, float> get_likelihood_field_score(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                              const sensor_msgs::msg::LaserScan &scan,
                                                              const nav_msgs::msg::OccupancyGrid &map,
                                                              const int &lidar_sampling_step,
                                                              const bool &enable_visualization = false);

    private:
        float sigma_hit_ = 0.2f;
        float z_hit_ = 1.0f;
        float z_rand_ = 0.0f;
        int map_occupied_threshold_ = 50;

        float gaussian_prob(float dist);

        rclcpp::Node::SharedPtr node_;
        rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr debug_cloud_pub_;
    };
}

#endif