#ifndef GLOBAL_EXPLORATION_H
#define GLOBAL_EXPLORATION_H

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
#include <boost/geometry.hpp>
#include <boost/geometry/index/rtree.hpp>

using namespace std;

namespace global_exploration
{
    namespace bg = boost::geometry;
    namespace bgi = boost::geometry::index;
    typedef bg::model::point<float, 2, bg::cs::cartesian> BGPoint;
    typedef pair<BGPoint, size_t> RTreeValue;

    class global_explorer
    {
    public:
        global_explorer(const float &min_expand_dist, const float &max_expand_dist, const float &min_dist_to_obs,
                        const float &frontier_points_min_dist, const float &sensing_radius,
                        const int &free_threshold = 30, const int &occupied_threshold = 55);
        ~global_explorer() {};

        void initialize();
        void reset();
        void stop();
        rrt_nodes get_frontier_points();
        float get_rrt_memory_in_mb();

    private:
        float min_expand_dist_, max_expand_dist_;
        float min_dist_to_obs_;
        float frontier_points_min_dist_;
        float sensing_radius_;
        float current_map_x_, current_map_y_, start_x_, start_y_;

        unique_ptr<ros::NodeHandle> node_handle_;

        unique_ptr<tf2_ros::Buffer> tf_buffer_;
        unique_ptr<tf2_ros::TransformListener> tf_listener_;

        ros::Subscriber map_sub_;

        ros::Publisher rrt_node_marker_array_pub_;
        ros::Publisher rrt_frontier_node_marker_array_pub_;
        ros::Publisher rrt_line_marker_array_pub_;

        visualization_msgs::MarkerArray rrt_node_marker_array_;
        // visualization_msgs::MarkerArray rrt_node_to_del_marker_array_;
        visualization_msgs::MarkerArray rrt_line_marker_array_;
        // visualization_msgs::MarkerArray rrt_line_to_del_marker_array_;
        visualization_msgs::MarkerArray rrt_frontier_node_marker_array_;

        geometry_msgs::TransformStamped tf_map_to_base_link_;
        geometry_msgs::Point32 origin_;

        int free_threshold_, occupied_threshold_;

        nav_msgs::OccupancyGrid map_data_;
        vector<float> min_dist_to_obs_table_;

        mutex mutex_data_;

        unique_ptr<random_device> random_device_;
        unique_ptr<mt19937> random_generator_;
        unique_ptr<uniform_real_distribution<float>> gen_random_number_;

        int node_index_ = 0;
        rrt_nodes rrt_tree_;
        rrt_nodes frontier_points_;

        bgi::rtree<RTreeValue, bgi::quadratic<16>> rtree_;
        vector<BGPoint> rtree_points_;

        bool sampling_ = false;

        void map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg);
        void thread_loop();
        float generate_random_number();
    };
}

#endif