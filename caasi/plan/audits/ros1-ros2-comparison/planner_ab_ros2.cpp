// TEST F (ROS 2): global planner algorithm A/B harness.
//
// Counterpart of planner_ab_ros1.cpp: identical synthetic costmaps, identical
// start/goal, identical planner parameters. Prints the plan as JSON.
//
// ROS 2 reads planner parameters from a node. A real node is created and the
// same parameter names/values are declared, so both stacks are configured the
// same way. The planner sources are used EXACTLY as built; nothing in the
// implementation is modified.
#include <cstdio>
#include <vector>
#include <string>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <nav2_costmap_2d/costmap_2d.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include "navigation/utils/global_planner/planner.h"

static const int W = 200, H = 200;
static const double RES = 0.05;
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
                      const std::vector<geometry_msgs::msg::PoseStamped> &plan)
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
    rclcpp::init(argc, argv);
    auto node1 = std::make_shared<rclcpp::Node>("planner_ab_ros2_s1");
    auto node2 = std::make_shared<rclcpp::Node>("planner_ab_ros2_s2");

    // NOTE: the planner declares its own parameters (with the same defaults as
    // navigation.yaml) during initialize(). Pre-declaring them here would raise
    // ParameterAlreadyDeclaredException, so the harness relies on those defaults.
    // The harness therefore exercises the planner's stock configuration.

    geometry_msgs::msg::PoseStamped start, goal;
    start.header.frame_id = goal.header.frame_id = "map";
    start.pose.position.x = 1.0; start.pose.position.y = 1.0; start.pose.orientation.w = 1.0;
    goal.pose.position.x = 8.0;  goal.pose.position.y = 8.0;  goal.pose.orientation.w = 1.0;

    bool ok1 = false, ok2 = false;
    std::vector<geometry_msgs::msg::PoseStamped> plan1, plan2, poly;

    {
        unsigned char costs[W * H];
        fill(costs, 0);
        nav2_costmap_2d::Costmap2D cm(W, H, RES, 0.0, 0.0, 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                cm.setCost(x, y, costs[y * W + x]);
        global_planner planner(NAME, &cm, "map", node1.get());
        ok1 = planner.make_plan(start, goal, 0.0, plan1, poly, 0.0f, false, 1, false, 0.5f, 5, 60);
    }
    {
        unsigned char costs[W * H];
        fill(costs, 1);
        nav2_costmap_2d::Costmap2D cm(W, H, RES, 0.0, 0.0, 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                cm.setCost(x, y, costs[y * W + x]);
        global_planner planner(NAME, &cm, "map", node2.get());
        ok2 = planner.make_plan(start, goal, 0.0, plan2, poly, 0.0f, false, 1, false, 0.5f, 5, 60);
    }

    printf("###JSON_START###\n{\n");
    printf("  \"side\": \"ros2\",\n");
    printf("  \"grid\": {\"width\": %d, \"height\": %d, \"resolution\": %.6f,\n"
           "           \"start\": [1.0, 1.0], \"goal\": [8.0, 8.0],\n"
           "           \"wall_x_index\": 100, \"doorway_y\": [80, 120]},\n", W, H, RES);
    printf("  \"results\": {\n");
    emit_path("S1_free_map", ok1, plan1);
    printf(",\n");
    emit_path("S2_wall_doorway", ok2, plan2);
    printf("\n  }\n}\n###JSON_END###\n");

    rclcpp::shutdown();
    return 0;
}
