#ifndef GLOBAL_EXPLORATION_H
#define GLOBAL_EXPLORATION_H

#include <rclcpp/rclcpp.hpp>
#include <thread>
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
        ~global_explorer()
        {
            stop_flag_ = true;

            if (rrt_thread_.joinable())
            {
                rrt_thread_.join();
            }
        };

        void initialize(rclcpp::Node::SharedPtr node);
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

        rclcpp::Node::SharedPtr node_;

        unique_ptr<tf2_ros::Buffer> tf_buffer_;
        unique_ptr<tf2_ros::TransformListener> tf_listener_;

        rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub_;
        rclcpp::CallbackGroup::SharedPtr map_callback_group_;
        rclcpp::executors::SingleThreadedExecutor::UniquePtr map_executor_;
        thread rrt_thread_;

        rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr rrt_node_marker_array_pub_;
        rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr rrt_frontier_node_marker_array_pub_;
        rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr rrt_line_marker_array_pub_;

        visualization_msgs::msg::MarkerArray rrt_node_marker_array_;
        // visualization_msgs::msg::MarkerArray rrt_node_to_del_marker_array_;
        visualization_msgs::msg::MarkerArray rrt_line_marker_array_;
        // visualization_msgs::msg::MarkerArray rrt_line_to_del_marker_array_;
        visualization_msgs::msg::MarkerArray rrt_frontier_node_marker_array_;

        geometry_msgs::msg::TransformStamped tf_map_to_base_link_;
        geometry_msgs::msg::Point32 origin_;

        int free_threshold_, occupied_threshold_;

        nav_msgs::msg::OccupancyGrid map_data_;
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
        bool stop_flag_ = false;

        void map_callback(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr &msg);
        void thread_loop();
        float generate_random_number();
    };
}

#endif