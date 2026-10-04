// TEST F (ROS 1): global planner algorithm A/B harness.
//
// Calls the ROS 1 global planner's make_plan() on DETERMINISTIC synthetic
// costmaps with fixed start/goal, and prints the resulting path as JSON for
// numeric comparison with the ROS 2 planner.
//
// Two sub-scenarios, both fully specified here (no simulator, no map file):
//   S1  free map   : 200x200 @ 0.05 m, all free,  start (1,1) -> goal (8,8)
//   S2  wall+door  : same grid, lethal vertical wall at x-index 100 with a
//                    doorway gap at y-index 80..120
//
// Parameters are set in the namespaces the planner actually reads:
//   private_nh = "~/" + name  -> /planner_ab_ros1/global_planner/<param>
//   global_nh  = "~"          -> /planner_ab_ros1/footprint
// Values match the project's navigation.yaml global_planner section.
//
// The planner sources are used EXACTLY as built in the workspace; nothing in
// the implementation is modified for this harness.
#include <cstdio>
#include <vector>
#include <string>
#include <ros/ros.h>
#include <xmlrpcpp/XmlRpcValue.h>
#include <costmap_2d/costmap_2d.h>
#include <geometry_msgs/PoseStamped.h>
#include "navigation/utils/global_planner/planner.h"

static const int W = 200, H = 200;
static const double RES = 0.05;
static const char *NODE = "planner_ab_ros1";
static const char *NAME = "global_planner";

static void fill(unsigned char *costs, int mode)
{
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
        {
            unsigned char c = 0;
            if (mode == 1 && x == 100 && !(y >= 80 && y <= 120))
                c = 254;
            costs[y * W + x] = c;
        }
}

static void emit_path(const char *label, bool ok,
                      const std::vector<geometry_msgs::PoseStamped> &plan)
{
    printf("    \"%s\": {\"success\": %s, \"plan_len\": %zu, \"plan\": [",
           label, ok ? "true" : "false", plan.size());
    for (size_t i = 0; i < plan.size(); ++i)
        printf("%s[%.6f,%.6f]", i ? "," : "",
               plan[i].pose.position.x, plan[i].pose.position.y);
    printf("]}");
}

int main(int argc, char **argv)
{
    ros::init(argc, argv, NODE);
    ros::NodeHandle nh("~");

    const std::string P = std::string("/") + NODE + "/" + NAME + "/";
    ros::param::set(P + "old_navfn_behavior", false);
    ros::param::set(P + "use_quadratic", true);
    ros::param::set(P + "use_grid_path", false);
    ros::param::set(P + "allow_unknown", true);
    ros::param::set(P + "default_tolerance", 0.0);
    ros::param::set(P + "visualize_potential", false);
    ros::param::set(P + "lethal_cost", 200);
    ros::param::set(P + "neutral_cost", 66);
    ros::param::set(P + "cost_factor", 0.6);
    ros::param::set(P + "min_dist_to_obs", 0.0);
    ros::param::set(P + "occupied_threshold", 60);

    XmlRpc::XmlRpcValue fp;
    fp.setSize(4);
    const double pts[4][2] = {{0.27, 0.22}, {0.27, -0.22}, {-0.27, -0.22}, {-0.27, 0.22}};
    for (int i = 0; i < 4; ++i) { fp[i].setSize(2); fp[i][0] = pts[i][0]; fp[i][1] = pts[i][1]; }
    ros::param::set(std::string("/") + NODE + "/footprint", fp);

    geometry_msgs::PoseStamped start, goal;
    start.header.frame_id = goal.header.frame_id = "map";
    start.pose.position.x = 1.0; start.pose.position.y = 1.0; start.pose.orientation.w = 1.0;
    goal.pose.position.x = 8.0;  goal.pose.position.y = 8.0;  goal.pose.orientation.w = 1.0;

    bool ok1 = false, ok2 = false;
    std::vector<geometry_msgs::PoseStamped> plan1, plan2, poly;

    {
        unsigned char costs[W * H];
        fill(costs, 0);
        costmap_2d::Costmap2D cm(W, H, RES, 0.0, 0.0, 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                cm.setCost(x, y, costs[y * W + x]);
        global_planner planner(NAME, &cm, "map");
        ok1 = planner.make_plan(start, goal, 0.0, plan1, poly, 0.0f, false, 1, false, 0.5f, 5, 60);
    }
    {
        unsigned char costs[W * H];
        fill(costs, 1);
        costmap_2d::Costmap2D cm(W, H, RES, 0.0, 0.0, 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                cm.setCost(x, y, costs[y * W + x]);
        global_planner planner(NAME, &cm, "map");
        ok2 = planner.make_plan(start, goal, 0.0, plan2, poly, 0.0f, false, 1, false, 0.5f, 5, 60);
    }

    printf("###JSON_START###\n{\n");
    printf("  \"side\": \"ros1\",\n");
    printf("  \"grid\": {\"width\": %d, \"height\": %d, \"resolution\": %.6f,\n"
           "           \"start\": [1.0, 1.0], \"goal\": [8.0, 8.0],\n"
           "           \"wall_x_index\": 100, \"doorway_y\": [80, 120]},\n", W, H, RES);
    printf("  \"results\": {\n");
    emit_path("S1_free_map", ok1, plan1);
    printf(",\n");
    emit_path("S2_wall_doorway", ok2, plan2);
    printf("\n  }\n}\n###JSON_END###\n");
    return 0;
}
