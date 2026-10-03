#ifndef PLANNER_WITH_COSTMAP_H
#define PLANNER_WITH_COSTMAP_H

#include <ros/ros.h>
#include <boost/shared_ptr.hpp>
#include <costmap_2d/costmap_2d_ros.h>
#include <tf2_ros/transform_listener.h>
#include "navigation/utils/global_planner/planner.h"
#include "navigation/navigation_state_code.h"
#include "localization/localization_sources.h"
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <pcl/kdtree/kdtree_flann.h>
#include "navigation/utils/math_utils.h"
#include <nav_msgs/OccupancyGrid.h>

#define COST_MAP_WAIT_UPDATE_DURATION 2.0
#define COST_MAP_WAIT_DURATION 5.0

namespace cm = costmap_2d;
namespace rm = geometry_msgs;

using cm::Costmap2D;
using cm::Costmap2DROS;
using rm::PoseStamped;
using std::string;
using std::vector;
using namespace std;

// 全局规划器
class planner_with_costmap : public global_planner
{
public:
    planner_with_costmap(string name, Costmap2DROS *cmap, ros::Time time) : global_planner(name, cmap->getCostmap(), cmap->getGlobalFrameID())
    {
        cmap_ = cmap;

        time_ = time;
    }

    tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan(geometry_msgs::PoseStamped &start, geometry_msgs::PoseStamped &goal,
                                                                                             float min_dist_to_obs = 0.4,
                                                                                             bool optimize = false,
                                                                                             int sampling_grid_dist = 1,
                                                                                             bool polyline = false,
                                                                                             float polyline_sample_max_dist = 0.5,
                                                                                             int polyline_sample_step = 5,
                                                                                             int occupied_threshold = 55);

    tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan(geometry_msgs::PoseStamped &start, geometry_msgs::PoseStamped &goal,
                                                                                             nav_msgs::OccupancyGrid &grid,
                                                                                             float min_dist_to_obs = 0.4,
                                                                                             bool optimize = false,
                                                                                             int sampling_grid_dist = 1,
                                                                                             bool polyline = false,
                                                                                             float polyline_sample_max_dist = 0.5,
                                                                                             int polyline_sample_step = 5,
                                                                                             int occupied_threshold = 55);

    tuple<bool, unsigned int, unsigned int> world_to_map(geometry_msgs::Pose pose);

    tuple<bool, unsigned int, unsigned int> world_to_map(geometry_msgs::PoseStamped pose) { return world_to_map(pose.pose); }

    tuple<bool, unsigned int, unsigned int> world_to_map(geometry_msgs::PoseWithCovarianceStamped pose) { return world_to_map(pose.pose.pose); }

    tuple<int, int> get_edge_point_index_in_map(geometry_msgs::PoseWithCovarianceStamped pose, vector<geometry_msgs::PoseStamped> path, int robot_pose_index = -1);

private:
    Costmap2DROS *cmap_;
    ros::Time time_;
};

// 机器人坐标查找器
class robot_pose_index_finder
{
public:
    robot_pose_index_finder()
    {
        cloud_.reset(new pcl::PointCloud<pcl::PointXYZ>);

        empty_ = true;
    }

    ~robot_pose_index_finder()
    {
        if (cloud_)
        {
            cloud_.reset();
        }
    }

    void set_path(vector<geometry_msgs::PoseStamped> path, bool use_kdtree = false);
    int get_index(geometry_msgs::PoseWithCovarianceStamped robot_pose, int start = -1, int end = -1, int thread_num = 4);
    bool is_empty() { return empty_; }

private:
    vector<geometry_msgs::PoseStamped> path_;
    bool use_kdtree_;
    pcl::KdTreeFLANN<pcl::PointXYZ> kdtree_;
    pcl::PointCloud<pcl::PointXYZ>::Ptr cloud_;
    bool empty_;

    struct closet_point_info
    {
        int index;
        double distance;
    };

    static void find_closest_point(const geometry_msgs::PoseWithCovarianceStamped &robot_pose,
                                   const std::vector<geometry_msgs::PoseStamped> &path,
                                   int start, int end, closet_point_info &result);
};

#endif