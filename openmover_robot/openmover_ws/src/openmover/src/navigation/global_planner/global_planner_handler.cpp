// 2022-5-18 0.0.0.2A

#include <navfn/MakeNavPlan.h>
#include <boost/shared_ptr.hpp>
#include <costmap_2d/costmap_2d_ros.h>
#include <tf2_ros/transform_listener.h>
#include "navigation/utils/global_planner/planner.h"
#include "localization/localization_sources.h"

#define NODE_NAME "global_planner_handler"
#define TAG "全局路径规划器"

#define COST_MAP_WAIT_UPDATE_DURATION 2.0
#define COST_MAP_WAIT_DURATION 5.0

namespace cm = costmap_2d;
namespace rm = geometry_msgs;

using cm::Costmap2D;
using cm::Costmap2DROS;
using rm::PoseStamped;
using std::string;
using std::vector;

class dijkstra_planner : public global_planner
{
public:
    dijkstra_planner(string name, Costmap2DROS *cmap, ros::Time time) : global_planner(name, cmap->getCostmap(), cmap->getGlobalFrameID())
    {
        ros::NodeHandle node_handle("~");
        cmap_ = cmap;

        time_ = time;

        make_plan_service_ = node_handle.advertiseService("make_plan", &dijkstra_planner::plan_request_callback, this);
    }

    bool plan_request_callback(navfn::MakeNavPlan::Request &req, navfn::MakeNavPlan::Response &resp)
    {
        ROS_INFO("%s：开始规划全局路径。", TAG);

        vector<PoseStamped> path;
        vector<PoseStamped> polyline_path;

        req.start.header.frame_id = LOCALIZATION_MAP;
        req.goal.header.frame_id = LOCALIZATION_MAP;

        // 判断 costmap 是否可用
        while (!cmap_->isCurrent())
        {
            ros::Duration(COST_MAP_WAIT_UPDATE_DURATION).sleep();
        }

        // 判断是否已等待代价地图
        if (ros::Time::now() - time_ < ros::Duration(COST_MAP_WAIT_DURATION))
        {
            ros::Duration(COST_MAP_WAIT_DURATION).sleep();
        }

        bool success = make_plan(req.start, req.goal, path, polyline_path, min_dist_to_obs_default_, true, 1, false, 2.0, 8, occupied_threshold_default_);

        resp.plan_found = success;

        if (success)
        {
            ROS_INFO("%s：全局路径规划成功。", TAG);

            resp.path = path;
        }
        else
        {
            ROS_WARN("%s：全局路径规划失败。", TAG);
        }

        return true;
    }

private:
    Costmap2DROS *cmap_;
    ros::ServiceServer make_plan_service_;
    ros::Subscriber pose_sub_;
    ros::Time time_;
};

int main(int argc, char **argv)
{
    // 初始化ROS节点
    ros::init(argc, argv, NODE_NAME);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 打印调试信息
    ROS_INFO("%s：节点已启动。", TAG);

    tf2_ros::Buffer buffer(ros::Duration(10));
    tf2_ros::TransformListener tf(buffer);

    costmap_2d::Costmap2DROS lcr("global_costmap", buffer);

    dijkstra_planner pppp("global_planner", &lcr, ros::Time::now());

    ros::spin();

    return 0;
}
