// ROS 2 port of the ROS 1 simulation_handler node.
// Structure and comments intentionally kept close to the original for comparability.

// 2022-4-25 0.0.0.1A

#include <rclcpp/rclcpp.hpp>

#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <openmover_msgs/srv/stop_request.hpp>
#include <openmover_msgs/srv/cmd_vel_mode_request.hpp>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"
#include "navigation/navigation_state_code.h"

#define NODE_NAME "simulation_handler"
#define TAG "机器人仿真控制器"

using namespace std;

// 定义速度控制模式
bool cmd_vel_manual_mode = true;

// 定义仿真速度发布器
rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sim_pub;

// 定义里程计与速度发布器
rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr odom_pub;
rclcpp::Publisher<geometry_msgs::msg::TwistWithCovarianceStamped>::SharedPtr twist_pub;

// 定义里程计与速度数据
geometry_msgs::msg::PoseWithCovarianceStamped odom_data;
geometry_msgs::msg::TwistWithCovarianceStamped twist_data;

// 定义紧急制动
bool emergency_flag = false;

void cmd_vel_mode_service_callback(const std::shared_ptr<rmw_request_id_t> request_header,
                                   const std::shared_ptr<openmover_msgs::srv::CmdVelModeRequest::Request> req,
                                   std::shared_ptr<openmover_msgs::srv::CmdVelModeRequest::Response> resp)
{
    (void)request_header;

    cmd_vel_manual_mode = req->manual;

    resp->result = CMD_RESPONSE_OK;
}

void cmd_vel_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
    if (!cmd_vel_manual_mode)
    {
        geometry_msgs::msg::Twist twist;

        if (!emergency_flag)
        {
            twist = *msg;
        }

        cmd_vel_sim_pub->publish(twist);
    }
}

void cmd_vel_manual_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
    if (cmd_vel_manual_mode)
    {
        geometry_msgs::msg::Twist twist;

        if (!emergency_flag)
        {
            twist = *msg;
        }

        cmd_vel_sim_pub->publish(twist);
    }
}

void odom_legacy_callback(const nav_msgs::msg::Odometry::SharedPtr msg)
{
    odom_data.header = msg->header;
    odom_data.pose = msg->pose;

    odom_pub->publish(odom_data);

    twist_data.header = msg->header;
    twist_data.twist = msg->twist;

    twist_pub->publish(twist_data);
}

void stop_service_callback(const std::shared_ptr<rmw_request_id_t> request_header,
                           const std::shared_ptr<openmover_msgs::srv::StopRequest::Request> req,
                           std::shared_ptr<openmover_msgs::srv::StopRequest::Response> resp)
{
    (void)request_header;

    emergency_flag = req->enable;

    resp->result = CMD_RESPONSE_OK;
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    rclcpp::init(argc, argv);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 定义ROS节点处理程序
    auto node_handle = rclcpp::Node::make_shared(NODE_NAME);

    // 打印调试信息
    RCLCPP_INFO(node_handle->get_logger(), "%s：节点已启动。", TAG);

    // 定义速度发布模式
    rclcpp::Service<openmover_msgs::srv::CmdVelModeRequest>::SharedPtr cmd_vel_mode_server =
        node_handle->create_service<openmover_msgs::srv::CmdVelModeRequest>(
            "openmover/control/cmd_vel_mode/request", cmd_vel_mode_service_callback);

    // 定义速度订阅器
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub =
        node_handle->create_subscription<geometry_msgs::msg::Twist>(
            "openmover/control/cmd_vel", 10, cmd_vel_callback);
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_manual_sub =
        node_handle->create_subscription<geometry_msgs::msg::Twist>(
            "openmover/control/cmd_vel_manual", 10, cmd_vel_manual_callback);

    // 定义传统里程计订阅器
    rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sim_sub =
        node_handle->create_subscription<nav_msgs::msg::Odometry>(
            "openmover/hardware/odom_sim", 10, odom_legacy_callback);

    // 定义紧急制动服务
    rclcpp::Service<openmover_msgs::srv::StopRequest>::SharedPtr stop_server =
        node_handle->create_service<openmover_msgs::srv::StopRequest>(
            "openmover/control/stop/request", stop_service_callback);

    // 定义里程计与速度发布器
    odom_pub = node_handle->create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("openmover/hardware/odom", 2);
    twist_pub = node_handle->create_publisher<geometry_msgs::msg::TwistWithCovarianceStamped>("openmover/hardware/twist", 2);

    // 定义速度发布器
    cmd_vel_sim_pub = node_handle->create_publisher<geometry_msgs::msg::Twist>("openmover/control/cmd_vel_sim", 1);

    rclcpp::spin(node_handle);

    rclcpp::shutdown();

    return 0;
}
