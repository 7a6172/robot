#ifndef LIKELIHOOD_FIELD_H
#define LIKELIHOOD_FIELD_H

#include <rclcpp/rclcpp.hpp>
#include <random>
#include <map>
#include <unordered_map>
#include <navigation/utils/math_utils.h>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2/utils.hpp>
#include <tf2_ros/transform_listener.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <localization/localization_sources.h>

using namespace std;

namespace likelihood_field
{
    class likelihood_field_model
    {
    public:
        likelihood_field_model(const float &sigma_hit = 0.2f, const float &z_hit = 1.0f, const float &z_rand = 0.0f, const int &map_occupied_threshold = 50,
                               rclcpp::Node *node = nullptr);
        ~likelihood_field_model() {};

        tuple<float, float> get_likelihood_field_score(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                       const sensor_msgs::msg::LaserScan &scan,
                                                       const nav_msgs::msg::OccupancyGrid &map,
                                                       const vector<float> &obs_dist_table,
                                                       const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score_no_cut_no_consis(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                                        const sensor_msgs::msg::LaserScan &scan,
                                                                        const nav_msgs::msg::OccupancyGrid &map,
                                                                        const vector<float> &obs_dist_table,
                                                                        const bool &enable_visualization = false);
        tuple<float, float, float> get_likelihood_field_score_new(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                                  const sensor_msgs::msg::LaserScan &scan,
                                                                  const nav_msgs::msg::OccupancyGrid &map,
                                                                  const vector<float> &obs_dist_table,
                                                                  const bool &enable_visualization = false);
        float get_likelihood_field_score_legacy(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                const sensor_msgs::msg::LaserScan &scan,
                                                const nav_msgs::msg::OccupancyGrid &map,
                                                const vector<float> &obs_dist_table,
                                                const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                       const sensor_msgs::msg::LaserScan &scan,
                                                       const nav_msgs::msg::OccupancyGrid &map,
                                                       const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score_no_cut_no_consis(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                                        const sensor_msgs::msg::LaserScan &scan,
                                                                        const nav_msgs::msg::OccupancyGrid &map,
                                                                        const bool &enable_visualization = false);
        tuple<float, float, float> get_likelihood_field_score_new(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                                  const sensor_msgs::msg::LaserScan &scan,
                                                                  const nav_msgs::msg::OccupancyGrid &map,
                                                                  const bool &enable_visualization = false);
        float get_likelihood_field_score_legacy(const geometry_msgs::msg::TransformStamped &tf_map_to_lidar,
                                                const sensor_msgs::msg::LaserScan &scan,
                                                const nav_msgs::msg::OccupancyGrid &map,
                                                const bool &enable_visualization = false);

    private:
        float sigma_hit_ = 0.2f;
        float z_hit_ = 1.0f;
        float z_rand_ = 0.0f;
        int map_occupied_threshold_ = 50;

        float gaussian_prob(float dist);

        // ROS 1 版本使用成员 ros::NodeHandle，ROS 2 中由外部节点传入（可为空，空则不发布调试点云）
        rclcpp::Node *node_ = nullptr;
        rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr debug_cloud_pub_;
    };
}

#endif
