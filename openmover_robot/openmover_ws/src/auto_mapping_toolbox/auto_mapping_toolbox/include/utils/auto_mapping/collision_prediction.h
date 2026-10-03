#ifndef COLLISION_PREDICTION_H
#define COLLISION_PREDICTION_H

#include <ros/ros.h>
#include <random>
#include <map>
#include <unordered_map>
#include <utils/math_utils.h>
#include <utils/auto_mapping/rrt_common.h>
#include <nav_msgs/OccupancyGrid.h>
#include <visualization_msgs/MarkerArray.h>
#include <tf/tf.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <sensor_msgs/LaserScan.h>

using namespace std;

namespace collision_prediction
{
    class collision_predictor
    {
    public:
        collision_predictor(const bool &use_external_dist_table = false, const int &free_threshold = 30, const int &occupied_threshold = 55);
        ~collision_predictor() {};

        void initialize();
        bool check(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const int &step,
                   const float &min_dist_to_obs, const nav_msgs::OccupancyGrid &grid,
                   const vector<float> &obs_dist_table,
                   const int &free_threshold, const int &occupied_threshold);
        bool check(const geometry_msgs::PoseStamped &p0, const geometry_msgs::PoseStamped &p1, const int &step,
                   const float &min_dist_to_obs, const nav_msgs::OccupancyGrid &grid,
                   const vector<float> &obs_dist_table,
                   const int &free_threshold, const int &occupied_threshold);
        bool check(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const int &step,
                   const float &min_dist_to_obs);
        bool check(const geometry_msgs::PoseStamped &p0, const geometry_msgs::PoseStamped &p1, const int &step,
                   const float &min_dist_to_obs);

    private:
        unique_ptr<ros::NodeHandle> node_handle_;

        unique_ptr<tf2_ros::Buffer> tf_buffer_;
        unique_ptr<tf2_ros::TransformListener> tf_listener_;

        ros::Subscriber map_sub_;

        geometry_msgs::TransformStamped tf_map_to_base_link_;
        geometry_msgs::TransformStamped tf_map_to_lidar_link_;

        nav_msgs::OccupancyGrid map_data_;
        vector<float> min_dist_to_obs_table_;
        sensor_msgs::LaserScan scan_data_;

        std::mutex mutex_data_;

        bool use_external_dist_table_;
        int free_threshold_, occupied_threshold_;
        float min_dist_to_obs_ = 0.25;

        void map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg);
        void thread_loop();
    };
}

#endif