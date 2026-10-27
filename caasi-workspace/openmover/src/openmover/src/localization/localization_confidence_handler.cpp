#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <tf2/utils.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <nav_msgs/msg/odometry.hpp>
#include <relocalization_toolbox_msgs/srv/initial_pose_request.hpp>
#include <openmover_msgs/srv/direct_request.hpp>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <algorithm>
#include <limits>
#include <angles/angles.h>
#include <localization/utils/localization_confidence/likelihood_field.h>
#include <std_msgs/msg/float32.hpp>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"

#define NODE_NAME "localization_confidence_handler"
#define TAG "定位置信度管理"

using namespace std;
using namespace likelihood_field;

// 全局节点指针（供回调与主循环获取时间、日志）
rclcpp::Node *node = nullptr;

float update_frequency = 1.0f;
float sigma_hit = 0.2f;
float z_hit = 1.0f;
float z_rand = 0.0f;
float max_tolerance_dist = 1.0f;
int occupied_threshold = 50;

// 是否获取到地图数据标记
bool map_data_received = false;

// 地图数据
vector<nav_msgs::msg::OccupancyGrid> map_data_array;

// 是否获取到雷达数据标记
bool laser_scan_data_received = false;

// 扫描数据
vector<sensor_msgs::msg::LaserScan> laser_scan_data_array;

// 定义置信度发布器
rclcpp::Publisher<std_msgs::msg::Float32>::SharedPtr confidence_pub;

// 定义 tf 组件与变换
unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster;
unique_ptr<tf2_ros::Buffer> tf_buffer;
geometry_msgs::msg::TransformStamped tf_map_to_lidar;

// 定义似然场计算器
unique_ptr<likelihood_field_model> likelihood_field_calculator;

std_msgs::msg::Float32 confidence_msg;

// map 回调函数
void map_callback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
    if (map_data_array.size() > 100)
    {
        map_data_array.erase(map_data_array.begin());
    }

    map_data_array.emplace_back(*msg);

    map_data_received = true;
}

// laser_scan 回调函数
void laser_scan_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
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
    rclcpp::init(argc, argv);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 定义ROS节点
    auto node_ptr = rclcpp::Node::make_shared(NODE_NAME);
    node = node_ptr.get();

    // 打印调试信息
    RCLCPP_INFO(node->get_logger(), "%s：节点已启动。", TAG);

    // 定义ROS节点循环频率控制器
    rclcpp::Rate loop_rate(100);

    // 定义ROS参数获取程序
    // 获取参数
    update_frequency = node->declare_parameter<float>("localization_confidence.update_frequency", 5.0f);
    sigma_hit = node->declare_parameter<float>("localization_confidence.sigma_hit", 0.2f);
    z_hit = node->declare_parameter<float>("localization_confidence.z_hit", 1.0f);
    z_rand = node->declare_parameter<float>("localization_confidence.z_rand", 0.0f);
    max_tolerance_dist = node->declare_parameter<float>("localization_confidence.max_tolerance_dist", 3.0f);
    // The scan interface belongs to the hardware profile, not to this node: the lab fit
    // merges two scanners into the shared topic while a single 360 degree scanner publishes
    // /scan. Default preserves the historical topic so existing maps are unaffected.
    const std::string scan_topic = node->declare_parameter<std::string>(
        "localization_confidence.scan_topic", "openmover/hardware/lidar/scan");
    occupied_threshold = node->declare_parameter<int>("localization_confidence.occupied_threshold", 50);

    // 初始化 tf 组件
    tf_broadcaster = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster(node_ptr));
    tf_buffer = unique_ptr<tf2_ros::Buffer>(new tf2_ros::Buffer(node_ptr->get_clock()));
    tf_buffer->setUsingDedicatedThread(true);
    tf2_ros::TransformListener tf_listener(*tf_buffer, true);

    // 定义ROS节点执行程序
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(node_ptr);

    // map 订阅器
    auto map_sub = node_ptr->create_subscription<nav_msgs::msg::OccupancyGrid>(
        "openmover/mapping/map", rclcpp::QoS(1).reliable().transient_local(), map_callback);
    // 雷达订阅器
    auto laser_scan_sub = node_ptr->create_subscription<sensor_msgs::msg::LaserScan>(
        scan_topic, rclcpp::SensorDataQoS(), laser_scan_callback);

    // confidence 话题发布器
    confidence_pub = node_ptr->create_publisher<std_msgs::msg::Float32>("openmover/localization/confidence", 1);

    likelihood_field_calculator = unique_ptr<likelihood_field_model>(new likelihood_field_model(sigma_hit,
                                                                                                z_hit, z_rand,
                                                                                                occupied_threshold, node));

    rclcpp::Time last_update_time = node->now();

    tf_map_to_lidar.transform.rotation = quaternion_msg_from_yaw(0);

    while (rclcpp::ok())
    {
        // 注册回调
        executor.spin_some();

        if (laser_scan_data_received && map_data_received)
        {
            if (node->now() - last_update_time > rclcpp::Duration::from_seconds(1.0f / update_frequency))
            {
                last_update_time = node->now();

                // 获取最新 lidar 到 map 的变换
                try
                {
                    tf_map_to_lidar =
                        tf_buffer->lookupTransform(LOCALIZATION_MAP, LOCALIZATION_LIDAR_LINK, tf2::TimePointZero, tf2::durationFromSec(60));
                }
                catch (...)
                {
                    RCLCPP_WARN(node->get_logger(), "%s：无法获取 map 到 lidar_link 的变换。", TAG);

                    loop_rate.sleep();

                    continue;
                }

                // 根据变换的时间戳获得时间上与变换最接近的地图数据与雷达扫描数据
                nav_msgs::msg::OccupancyGrid map_data;
                sensor_msgs::msg::LaserScan laser_scan_data;

                const rclcpp::Time target_stamp = rclcpp::Time(tf_map_to_lidar.header.stamp);

                double best_map_dt = std::numeric_limits<double>::infinity();

                for (const auto &m : map_data_array)
                {
                    double dt = fabs((rclcpp::Time(m.header.stamp) - target_stamp).seconds());

                    if (dt < best_map_dt)
                    {
                        best_map_dt = dt;
                        map_data = m;
                    }
                }

                double best_scan_dt = std::numeric_limits<double>::infinity();

                for (const auto &s : laser_scan_data_array)
                {
                    double dt = fabs((rclcpp::Time(s.header.stamp) - target_stamp).seconds());

                    if (dt < best_scan_dt)
                    {
                        best_scan_dt = dt;
                        laser_scan_data = s;
                    }
                }

                if (best_scan_dt > 0.5)
                {
                    RCLCPP_WARN(node->get_logger(), "%s：未找到与变换时间足够接近的数据（Δt=%.3f / %.3f s），定位失效。",
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

                confidence_pub->publish(confidence_msg);
            }
        }

        // 循环频率控制
        loop_rate.sleep();
    }

    return 0;
}
