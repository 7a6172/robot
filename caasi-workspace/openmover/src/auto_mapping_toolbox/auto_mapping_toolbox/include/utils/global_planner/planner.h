// 2022-5-18 0.0.0.2A

#ifndef PLANNER_H
#define PLANNER_H

#define POT_HIGH 1.0e10

#include <rclcpp/rclcpp.hpp>
#include <nav2_costmap_2d/costmap_2d.hpp>
#include <nav2_costmap_2d/costmap_2d_ros.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/point.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav_msgs/msg/path.hpp>
#include <vector>
#include <nav_msgs/srv/get_plan.hpp>
#include "potential_calculator.h"
#include "expander.h"
#include "traceback.h"
#include "orientation_filter.h"
#include <utils/math_utils.h>
#include <utils/global_planner/backend_optimization.h>
#include <utils/global_planner/polyline_generation.h>
#include <omp.h>

class Expander;
class GridPath;

class global_planner
{
public:
    global_planner();
    global_planner(std::string name, nav2_costmap_2d::Costmap2D *costmap, std::string frame_id,
                   rclcpp::Node *node = nullptr);
    ~global_planner();

    void initialize(std::string name, nav2_costmap_2d::Costmap2DROS *costmap_ros, rclcpp::Node *node = nullptr);

    void initialize(std::string name, nav2_costmap_2d::Costmap2D *costmap, std::string frame_id,
                    rclcpp::Node *node = nullptr);

    bool make_plan(const geometry_msgs::msg::PoseStamped &start, const geometry_msgs::msg::PoseStamped &goal,
                   std::vector<geometry_msgs::msg::PoseStamped> &plan,
                   std::vector<geometry_msgs::msg::PoseStamped> &polyline_plan,
                   float min_dist_to_obs = 0.4,
                   bool optimize = false,
                   int sampling_grid_dist = 1,
                   bool polyline = false,
                   float polyline_sample_max_dist = 0.5,
                   int polyline_sample_step = 5,
                   int occupied_threshold = 60);

    bool make_plan(const geometry_msgs::msg::PoseStamped &start, const geometry_msgs::msg::PoseStamped &goal, double tolerance,
                   std::vector<geometry_msgs::msg::PoseStamped> &plan,
                   std::vector<geometry_msgs::msg::PoseStamped> &polyline_plan,
                   float min_dist_to_obs = 0.4,
                   bool optimize = false,
                   int sampling_grid_dist = 1,
                   bool polyline = false,
                   float polyline_sample_max_dist = 0.5,
                   int polyline_sample_step = 5,
                   int occupied_threshold = 60);

    bool make_plan(const geometry_msgs::msg::PoseStamped &start, const geometry_msgs::msg::PoseStamped &goal, double tolerance,
                   std::vector<geometry_msgs::msg::PoseStamped> &plan,
                   std::vector<geometry_msgs::msg::PoseStamped> &polyline_plan,
                   nav_msgs::msg::OccupancyGrid &grid,
                   float min_dist_to_obs = 0.4,
                   bool optimize = false,
                   int sampling_grid_dist = 1,
                   bool polyline = false,
                   float polyline_sample_max_dist = 0.5,
                   int polyline_sample_step = 5,
                   int occupied_threshold = 60);

    bool compute_potential(const geometry_msgs::msg::Point &world_point);

    bool get_plan_from_potential(double start_x, double start_y, double end_x, double end_y,
                                 const geometry_msgs::msg::PoseStamped &goal,
                                 std::vector<geometry_msgs::msg::PoseStamped> &plan,
                                 std::vector<geometry_msgs::msg::PoseStamped> &polyline_plan,
                                 float min_dist_to_obs = 0.4,
                                 bool optimize = false,
                                 int sampling_grid_dist = 1,
                                 bool polyline = false,
                                 float polyline_sample_max_dist = 0.5,
                                 int polyline_sample_step = 5);

    double get_point_potential(const geometry_msgs::msg::Point &world_point);

    bool valid_point_potential(const geometry_msgs::msg::Point &world_point);

    bool valid_point_potential(const geometry_msgs::msg::Point &world_point, double tolerance);

    void publish_plan(const std::vector<geometry_msgs::msg::PoseStamped> &path);

    void publish_polyline_plan(const std::vector<geometry_msgs::msg::PoseStamped> &path);

    int occupied_threshold_default_;
    float min_dist_to_obs_default_;

protected:
    nav2_costmap_2d::Costmap2D *costmap_;
    std::string frame_id_;
    rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr plan_pub_;
    rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr polyline_plan_pub_;
    bool initialized_, allow_unknown_;
    rclcpp::Node *node_ = nullptr;

private:
    void map_to_world(double mx, double my, double &wx, double &wy);

    bool world_to_map(double wx, double wy, double &mx, double &my);

    void clear_robot_cell(const geometry_msgs::msg::PoseStamped &global_pose, unsigned int mx, unsigned int my);

    void publish_potential(float *potential);

    double planner_window_x_, planner_window_y_, default_tolerance_;
    std::mutex mutex_;
    rclcpp::Service<nav_msgs::srv::GetPlan>::SharedPtr make_plan_srv_;

    PotentialCalculator *p_calc_;
    Expander *planner_;
    Traceback *path_maker_;
    OrientationFilter *orientation_filter_;

    bool publish_potential_;
    rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr potential_pub_;
    int publish_scale_;

    void outline_map(unsigned char *costarr, int nx, int ny, unsigned char value);

    float *potential_array_;
    unsigned int start_x_, start_y_, end_x_, end_y_;

    bool old_navfn_behavior_;
    float convert_offset_;

    bool outline_map_;

    int lethal_cost_;
    int neutral_cost_;
    double cost_factor_;

    unique_ptr<backend_optimization::backend_optimizer> path_optimizer;
    unique_ptr<polyline_generation::polyline_generator> path_polylineizer;
};

#endif
