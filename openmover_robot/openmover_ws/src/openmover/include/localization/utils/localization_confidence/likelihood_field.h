#ifndef LIKELIHOOD_FIELD_H
#define LIKELIHOOD_FIELD_H

#include <ros/ros.h>
#include <random>
#include <map>
#include <unordered_map>
#include <navigation/utils/math_utils.h>
#include <nav_msgs/OccupancyGrid.h>
#include <visualization_msgs/MarkerArray.h>
#include <tf/tf.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <sensor_msgs/LaserScan.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/TransformStamped.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/point_cloud2_iterator.h>
#include <localization/localization_sources.h>

using namespace std;

namespace likelihood_field
{
    class likelihood_field_model
    {
    public:
        likelihood_field_model(const float &sigma_hit = 0.2f, const float &z_hit = 1.0f, const float &z_rand = 0.0f, const int &map_occupied_threshold = 50);
        ~likelihood_field_model() {};

        tuple<float, float> get_likelihood_field_score(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                       const sensor_msgs::LaserScan &scan,
                                                       const nav_msgs::OccupancyGrid &map,
                                                       const vector<float> &obs_dist_table,
                                                       const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score_no_cut_no_consis(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                                        const sensor_msgs::LaserScan &scan,
                                                                        const nav_msgs::OccupancyGrid &map,
                                                                        const vector<float> &obs_dist_table,
                                                                        const bool &enable_visualization = false);
        tuple<float, float, float> get_likelihood_field_score_new(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                                  const sensor_msgs::LaserScan &scan,
                                                                  const nav_msgs::OccupancyGrid &map,
                                                                  const vector<float> &obs_dist_table,
                                                                  const bool &enable_visualization = false);
        float get_likelihood_field_score_legacy(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                const sensor_msgs::LaserScan &scan,
                                                const nav_msgs::OccupancyGrid &map,
                                                const vector<float> &obs_dist_table,
                                                const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                       const sensor_msgs::LaserScan &scan,
                                                       const nav_msgs::OccupancyGrid &map,
                                                       const bool &enable_visualization = false);
        tuple<float, float> get_likelihood_field_score_no_cut_no_consis(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                                        const sensor_msgs::LaserScan &scan,
                                                                        const nav_msgs::OccupancyGrid &map,
                                                                        const bool &enable_visualization = false);
        tuple<float, float, float> get_likelihood_field_score_new(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                                  const sensor_msgs::LaserScan &scan,
                                                                  const nav_msgs::OccupancyGrid &map,
                                                                  const bool &enable_visualization = false);
        float get_likelihood_field_score_legacy(const geometry_msgs::TransformStamped &tf_map_to_lidar,
                                                const sensor_msgs::LaserScan &scan,
                                                const nav_msgs::OccupancyGrid &map,
                                                const bool &enable_visualization = false);

    private:
        float sigma_hit_ = 0.2f;
        float z_hit_ = 1.0f;
        float z_rand_ = 0.0f;
        int map_occupied_threshold_ = 50;

        float gaussian_prob(float dist);

        ros::NodeHandle node_handle_;
        ros::Publisher debug_cloud_pub_;
    };
}

#endif