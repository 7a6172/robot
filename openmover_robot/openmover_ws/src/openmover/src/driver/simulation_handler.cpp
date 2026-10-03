// 2022-4-25 0.0.0.1A

#include <ros/ros.h>
#include <angles/angles.h>
#include <openmover_msgs/cmd_vel_mode_request.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <linux/input.h>
#include <geometry_msgs/Twist.h>
#include <nav_msgs/Odometry.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include <openmover_msgs/stop_request.h>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"
#include "navigation/navigation_state_code.h"

#define NODE_NAME "simulation_handler"
#define TAG "机器人仿真控制器"

using namespace std;

// 定义速度控制模式
bool cmd_vel_manual_mode = true;

// 定义仿真速度发布器
ros::Publisher cmd_vel_sim_pub;

// 定义里程计与速度发布器
ros::Publisher odom_pub;
ros::Publisher twist_pub;

// 定义里程计与速度数据
geometry_msgs::PoseWithCovarianceStamped odom_data;
geometry_msgs::TwistWithCovarianceStamped twist_data;

// 定义紧急制动
bool emergency_flag = false;

bool cmd_vel_mode_callback(openmover_msgs::cmd_vel_mode_request::Request &req, openmover_msgs::cmd_vel_mode_request::Response &resp)
{
    cmd_vel_manual_mode = req.manual;

    resp.result = CMD_RESPONSE_OK;

    return true;
}

void cmd_vel_callback(const geometry_msgs::Twist::ConstPtr &msg)
{
    if (!cmd_vel_manual_mode)
    {
        geometry_msgs::Twist twist;

        if (!emergency_flag)
        {
            twist = *msg;
        }

        cmd_vel_sim_pub.publish(twist);
    }
}

void cmd_vel_manual_callback(const geometry_msgs::Twist::ConstPtr &msg)
{
    if (cmd_vel_manual_mode)
    {
        geometry_msgs::Twist twist;

        if (!emergency_flag)
        {
            twist = *msg;
        }

        cmd_vel_sim_pub.publish(twist);
    }
}

void odom_legacy_callback(const nav_msgs::Odometry::ConstPtr &msg)
{
    odom_data.header = msg->header;
    odom_data.pose = msg->pose;

    odom_pub.publish(odom_data);

    twist_data.header = msg->header;
    twist_data.twist = msg->twist;

    twist_pub.publish(twist_data);
}

bool stop_callback(openmover_msgs::stop_request::Request &req, openmover_msgs::stop_request::Response &resp)
{
    emergency_flag = req.enable;

    resp.result = CMD_RESPONSE_OK;

    return true;
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    ros::init(argc, argv, NODE_NAME);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 打印调试信息
    ROS_INFO("%s：节点已启动。", TAG);

    // 定义ROS节点处理程序
    ros::NodeHandle node_handle;

    // 定义ROS参数获取程序
    ros::NodeHandle node_handle_param("~/simulation");

    // 定义速度发布模式
    ros::ServiceServer cmd_vel_mode_server = node_handle.advertiseService("openmover/control/cmd_vel_mode/request", cmd_vel_mode_callback);

    // 定义速度订阅器
    ros::Subscriber cmd_vel_sub = node_handle.subscribe<geometry_msgs::Twist>("openmover/control/cmd_vel", 10, cmd_vel_callback);
    ros::Subscriber cmd_vel_manual_sub = node_handle.subscribe<geometry_msgs::Twist>("openmover/control/cmd_vel_manual", 10, cmd_vel_manual_callback);

    // 定义传统里程计订阅器
    ros::Subscriber odom_sim_sub = node_handle.subscribe<nav_msgs::Odometry>("openmover/hardware/odom_sim", 10, odom_legacy_callback);

    // 定义紧急制动服务
    ros::ServiceServer stop_server = node_handle.advertiseService("openmover/control/stop/request", stop_callback);

    // 定义里程计与速度发布器
    odom_pub = node_handle.advertise<geometry_msgs::PoseWithCovarianceStamped>("openmover/hardware/odom", 2);
    twist_pub = node_handle.advertise<geometry_msgs::TwistWithCovarianceStamped>("openmover/hardware/twist", 2);

    // 定义速度发布器
    cmd_vel_sim_pub = node_handle.advertise<geometry_msgs::Twist>("openmover/control/cmd_vel_sim", 1);

    ros::spin();

    return 0;
}
