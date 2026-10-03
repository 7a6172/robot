#include <ros/ros.h>
#include <geometry_msgs/Twist.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <tf/tf.h>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <nav_msgs/Odometry.h>
#include <relocalization_toolbox_msgs/initial_pose_request.h>
#include <openmover_msgs/direct_request.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <algorithm>
#include <limits>
#include <angles/angles.h>
#include <localization/utils/localization_confidence/likelihood_field.h>
#include <std_msgs/Float32.h>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"

#define NODE_NAME "localization_confidence_handler"
#define TAG "定位置信度管理"

using namespace std;
using namespace likelihood_field;

float update_frequency = 1.0f;
float sigma_hit = 0.2f;
float z_hit = 1.0f;
float z_rand = 0.0f;
float max_tolerance_dist = 1.0f;
int occupied_threshold = 50;

// 是否获取到地图数据标记
bool map_data_received = false;

// 地图数据
vector<nav_msgs::OccupancyGrid> map_data_array;

// 是否获取到雷达数据标记
bool laser_scan_data_received = false;

// 扫描数据
vector<sensor_msgs::LaserScan> laser_scan_data_array;

// 定义置信度发布器
ros::Publisher confidence_pub;

// 定义 tf 组件与变换
unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster;
unique_ptr<tf2_ros::Buffer> tf_buffer;
geometry_msgs::TransformStamped tf_map_to_lidar;

// 定义似然场计算器
unique_ptr<likelihood_field_model> likelihood_field_calculator;

std_msgs::Float32 confidence_msg;

// map 回调函数
void map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg)
{
    if (map_data_array.size() > 100)
    {
        map_data_array.erase(map_data_array.begin());
    }

    map_data_array.emplace_back(*msg);

    map_data_received = true;
}

// laser_scan 回调函数
void laser_scan_callback(const sensor_msgs::LaserScan::ConstPtr &msg)
{
    if (laser_scan_data_array.size() > 100)
    {
        laser_scan_data_array.erase(laser_scan_data_array.begin());
    }

    laser_scan_data_array.emplace_back(*msg);

    laser_scan_data_received = true;
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

    // 定义ROS节点循环频率控制器
    ros::Rate loop_rate(100);

    // 定义ROS参数获取程序
    ros::NodeHandle node_handle_param("~/localization_confidence");
    ros::NodeHandle node_handle_param_global("~");

    // 获取参数
    node_handle_param.param<float>("update_frequency", update_frequency, 5);
    node_handle_param.param<float>("sigma_hit", sigma_hit, 0.2);
    node_handle_param.param<float>("z_hit", z_hit, 1.0);
    node_handle_param.param<float>("z_rand", z_rand, 0.0);
    node_handle_param.param<float>("max_tolerance_dist", max_tolerance_dist, 3.0);
    node_handle_param.param<int>("occupied_threshold", occupied_threshold, 50);

    // 初始化 tf 组件
    tf_broadcaster = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster);
    tf_buffer = unique_ptr<tf2_ros::Buffer>(new tf2_ros::Buffer);
    tf2_ros::TransformListener tf_listener(*tf_buffer);

    // map 订阅器
    ros::Subscriber map_sub = node_handle.subscribe("openmover/mapping/map", 1, map_callback);
    // 雷达订阅器
    ros::Subscriber laser_scan_sub = node_handle.subscribe("openmover/hardware/lidar/scan", 2, laser_scan_callback);

    // confidence 话题发布器
    confidence_pub = node_handle.advertise<std_msgs::Float32>("openmover/localization/confidence", 1);

    likelihood_field_calculator = unique_ptr<likelihood_field_model>(new likelihood_field_model(sigma_hit,
                                                                                                z_hit, z_rand,
                                                                                                occupied_threshold));

    ros::Time last_update_time = ros::Time::now();

    tf_map_to_lidar.transform.rotation = tf::createQuaternionMsgFromYaw(0);

    while (node_handle.ok())
    {
        // 注册回调
        ros::spinOnce();

        if (laser_scan_data_received && map_data_received)
        {
            if (ros::Time::now() - last_update_time > ros::Duration(1.0f / update_frequency))
            {
                last_update_time = ros::Time::now();

                // 获取最新 lidar 到 map 的变换
                try
                {
                    tf_map_to_lidar =
                        tf_buffer->lookupTransform(LOCALIZATION_MAP, LOCALIZATION_LIDAR_LINK, ros::Time(0), ros::Duration(60));
                }
                catch (...)
                {
                    ROS_WARN("%s：无法获取 map 到 lidar_link 的变换。", TAG);

                    loop_rate.sleep();

                    continue;
                }

                // 根据变换的时间戳获得时间上与变换最接近的地图数据与雷达扫描数据
                nav_msgs::OccupancyGrid map_data;
                sensor_msgs::LaserScan laser_scan_data;

                const ros::Time &target_stamp = tf_map_to_lidar.header.stamp;

                double best_map_dt = std::numeric_limits<double>::infinity();

                for (const auto &m : map_data_array)
                {
                    double dt = fabs((m.header.stamp - target_stamp).toSec());

                    if (dt < best_map_dt)
                    {
                        best_map_dt = dt;
                        map_data = m;
                    }
                }

                double best_scan_dt = std::numeric_limits<double>::infinity();

                for (const auto &s : laser_scan_data_array)
                {
                    double dt = fabs((s.header.stamp - target_stamp).toSec());

                    if (dt < best_scan_dt)
                    {
                        best_scan_dt = dt;
                        laser_scan_data = s;
                    }
                }

                if (best_scan_dt > 0.5)
                {
                    ROS_WARN("%s：未找到与变换时间足够接近的数据（Δt=%.3f / %.3f s），定位失效。",
                             TAG, best_map_dt, best_scan_dt);

                    confidence_msg.data = 0.0f;
                }
                else
                {
                    vector<float> distance_map = calc_min_dist_to_obs_table(map_data,
                                                                            tf_map_to_lidar.transform.translation.x,
                                                                            tf_map_to_lidar.transform.translation.y,
                                                                            laser_scan_data.range_max, occupied_threshold);

                    // 计算似然场评分
                    auto matching_result = likelihood_field_calculator->get_likelihood_field_score(
                        tf_map_to_lidar, laser_scan_data, map_data, distance_map);

                    // 发布置信度
                    float p = exp(get<0>(matching_result));
                    float mean_dist_to_obs = get<1>(matching_result);
                    mean_dist_to_obs = mean_dist_to_obs > max_tolerance_dist ? max_tolerance_dist : (mean_dist_to_obs < map_data.info.resolution / 2.0f ? map_data.info.resolution / 2.0f : mean_dist_to_obs);
                    float d_score = 1.0f - ((mean_dist_to_obs - (map_data.info.resolution / 2.0f)) / (max_tolerance_dist - (map_data.info.resolution / 2.0f)));
                    float confidence = sqrt(p * d_score);

                    confidence_msg.data = confidence;
                }

                confidence_pub.publish(confidence_msg);
            }
        }

        // 循环频率控制
        loop_rate.sleep();
    }

    return 0;
}