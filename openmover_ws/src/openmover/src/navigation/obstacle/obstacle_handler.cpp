// 2023-11-1 0.0.0.3A
// ROS 2 Jazzy port (Stage 5): faithful to ROS 1 obstacle_handler.
// - laser sub:     openmover/hardware/lidar/scan/obstacle
// - obstacle pub:  openmover/navigation/obstacle (20 Hz)
// - params:        obstacle.* (ROS 1 ~/obstacle) + footprint (flat array, see note)
// NOTE: ROS 1 footprint was a nested array ([[x,y],...]); ROS 2 Jazzy has no
// nested-array params, so it is a flat array [x1,y1,x2,y2,...] like in
// navigation_handler. If footprint is missing, chassis defaults 0.85x0.85 are
// kept (ROS 1 would crash on the missing param).

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <openmover_msgs/msg/obstacle.hpp>
#include <geometry_msgs/msg/polygon.hpp>
#include <geometry_msgs/msg/point32.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <pcl/point_cloud.h>
#include <pcl/common/transforms.h>
#include <tf2_eigen/tf2_eigen.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>
#include <tf2/time.h>

#include <cmath>
#include <memory>
#include <vector>

#include "localization/localization_sources.h"

#define NODE_NAME "obstacle_handler"
#define TAG "障碍检测"

using namespace std;

// 定义雷达距离参数
float laser_min_dist = 0.06;
float laser_max_dist = 20;

// 定义障碍物距离参数
float obs_min_dist = 0.06;

// 定义障碍数据清除超时
int obstacle_no_update_clear_timeout = 5;

// 足迹部分
geometry_msgs::msg::Polygon footprint_polygon;

// 定义底盘尺寸
float chassis_width = 0.85;
float chassis_length = 0.85;

// 定义网格数
int obstacle_grid_number = 5;

// 定义机器人雷达数据
sensor_msgs::msg::LaserScan laser_scan_data;

// 是否反转雷达 (y 是否取负)
bool ray_reversed = false;

// 定义obstacle发布器
rclcpp::Publisher<openmover_msgs::msg::Obstacle>::SharedPtr obstacle_pub;

// 定义obstacle数据
openmover_msgs::msg::Obstacle obstacle_data;

// 是否获取到雷达数据标记
bool laser_scan_data_ready = false;

// 定义 tf 组件与变换
unique_ptr<tf2_ros::Buffer> tf_buffer;
geometry_msgs::msg::TransformStamped tf_lidar_to_base;
Eigen::Affine3f affine_lidar_to_base;

// laser_scan回调函数
void laser_scan_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
{
	laser_scan_data = *msg;
	laser_scan_data_ready = true;
}

int main(int argc, char **argv)
{
	// 初始化ROS节点
	rclcpp::init(argc, argv);

	// 设置控制台本地化，以显示中文
	setlocale(LC_CTYPE, "zh_CN.utf8");

	// 定义ROS节点处理程序
	auto node = rclcpp::Node::make_shared(NODE_NAME);

	// 打印调试信息
	RCLCPP_INFO(node->get_logger(), "%s：节点已启动。", TAG);

	// 定义ROS节点循环频率控制器
	rclcpp::Rate loop_rate(20);

	// 获取参数（ROS 1 ~/obstacle 命名空间）
	laser_min_dist = node->declare_parameter<float>("obstacle.laser_min_dist", 0.06);
	laser_max_dist = node->declare_parameter<float>("obstacle.laser_max_dist", 20);
	obs_min_dist = node->declare_parameter<float>("obstacle.obs_min_dist", 0.06);

	obstacle_no_update_clear_timeout =
		node->declare_parameter<int>("obstacle.obstacle_no_update_clear_timeout", 20);

	// 足迹部分（ROS 1 全局 ~footprint，ROS 2 使用扁平数组）
	auto footprint_param = node->declare_parameter<vector<double>>("footprint", vector<double>());

	for (size_t i = 0; i + 1 < footprint_param.size(); i += 2)
	{
		geometry_msgs::msg::Point32 point;

		point.x = footprint_param[i];
		point.y = footprint_param[i + 1];

		footprint_polygon.points.push_back(point);
	}

	obstacle_grid_number = node->declare_parameter<int>("obstacle.obstacle_grid_number", 5);
	ray_reversed = node->declare_parameter<bool>("obstacle.ray_reversed", false);

	// 初始化 tf 组件
	tf_buffer = unique_ptr<tf2_ros::Buffer>(new tf2_ros::Buffer(node->get_clock()));
	tf2_ros::TransformListener tf_listener(*tf_buffer);

	// 监听雷达到基座的 tf 数据
	try
	{
		tf_lidar_to_base = tf_buffer->lookupTransform(
			LOCALIZATION_BASE_LINK, LOCALIZATION_LIDAR_LINK,
			tf2::TimePoint(), tf2::durationFromSec(60));
	}
	catch (tf2::TransformException &ex)
	{
		RCLCPP_FATAL(node->get_logger(), "%s：无法获取雷达到基座的TF：%s", TAG, ex.what());
		rclcpp::shutdown();
		return 1;
	}

	// 雷达到基座的变换
	affine_lidar_to_base = tf2::transformToEigen(tf_lidar_to_base.transform).matrix().cast<float>();

	// 计算底盘尺寸
	if (footprint_polygon.points.size() >= 4)
	{
		chassis_width = fabs(footprint_polygon.points[0].y - footprint_polygon.points[1].y);
		chassis_length = fabs(footprint_polygon.points[0].x - footprint_polygon.points[3].x);
	}
	else
	{
		RCLCPP_WARN(node->get_logger(), "%s：未提供足迹参数，使用默认底盘尺寸。", TAG);
	}

	RCLCPP_INFO(node->get_logger(), "%s：底盘长度：%f，底盘宽度：%f。", TAG, chassis_length, chassis_width);

	// 定义单个网格尺寸
	float obstacle_grid_size_width = chassis_width / obstacle_grid_number;
	float obstacle_grid_size_length = chassis_length / obstacle_grid_number;

	// 雷达订阅器
	auto laser_scan_sub = node->create_subscription<sensor_msgs::msg::LaserScan>(
		"openmover/hardware/lidar/scan/obstacle", rclcpp::SensorDataQoS(), laser_scan_callback);

	// obstacle 话题发布器
	obstacle_pub = node->create_publisher<openmover_msgs::msg::Obstacle>(
		"openmover/navigation/obstacle", 1);

	// 初始化obstacle数据
	obstacle_data.header.frame_id = LOCALIZATION_BASE_LINK;
	obstacle_data.size = obstacle_grid_number;

	// 初始化雷达数据
	std::vector<float> obstacle_laser_forward_data(obstacle_grid_number, INFINITY);
	std::vector<float> obstacle_laser_backward_data(obstacle_grid_number, INFINITY);
	std::vector<float> obstacle_laser_left_data(obstacle_grid_number, INFINITY);
	std::vector<float> obstacle_laser_right_data(obstacle_grid_number, INFINITY);
	obstacle_data.obstacle_forward = obstacle_laser_forward_data;
	obstacle_data.obstacle_backward = obstacle_laser_backward_data;
	obstacle_data.obstacle_left = obstacle_laser_left_data;
	obstacle_data.obstacle_right = obstacle_laser_right_data;

	std::vector<int> obstacle_laser_forward_update_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_backward_update_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_left_update_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_right_update_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_forward_noupdate_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_backward_noupdate_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_left_noupdate_counter(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_right_noupdate_counter(obstacle_grid_number, 0);

	std::vector<int> obstacle_laser_forward_current_data_init(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_backward_current_data_init(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_left_current_data_init(obstacle_grid_number, 0);
	std::vector<int> obstacle_laser_right_current_data_init(obstacle_grid_number, 0);

	while (rclcpp::ok())
	{
		// 注册回调
		rclcpp::spin_some(node);

		// 初始化obstacle数据
		obstacle_data.header.stamp = node->now();

		if (laser_scan_data_ready)
		{
			// 枚举 laser_scan
			size_t size = laser_scan_data.ranges.size();

			for (size_t i = 0; i < size; i++)
			{
				// 判断范围
				if (!isfinite(laser_scan_data.ranges[i]) ||
					laser_scan_data.ranges[i] < laser_min_dist ||
					laser_scan_data.ranges[i] > laser_max_dist)
				{
					continue;
				}

				// 坐标变换到雷达笛卡尔系
				float range = laser_scan_data.ranges[i];
				float angle = laser_scan_data.angle_min + i * laser_scan_data.angle_increment;
				pcl::PointXYZ point_lidar(range * cos(angle), range * sin(angle), 0);

				// 坐标变换到机器人本体笛卡尔系
				pcl::PointXYZ point_base_link = pcl::transformPoint(point_lidar, affine_lidar_to_base);

				// y 是否反转
				if (ray_reversed)
				{
					point_base_link.y *= -1.0f;
				}

				// 栅格下标
				int grid_index = 0;

				// 判断是否在前栅格
				// 4 3 2 1 0
				if (point_base_link.x > 0 &&
					fabs(point_base_link.x) - chassis_length / 2.0f >= obs_min_dist &&
					fabs(point_base_link.y) <= chassis_width / 2.0f)
				{
					grid_index = (int)(point_base_link.y / obstacle_grid_size_width + obstacle_grid_number / 2);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_forward_current_data_init[grid_index])
					{
						obstacle_laser_forward_current_data_init[grid_index] = 1;
						obstacle_laser_forward_data[grid_index] = fabs(point_base_link.x) - chassis_length / 2.0f;
					}
					else
					{
						obstacle_laser_forward_data[grid_index] = min(obstacle_laser_forward_data[grid_index], fabs(point_base_link.x) - chassis_length / 2.0f);
					}

					obstacle_laser_forward_noupdate_counter[grid_index] = 0;
				}
				// 判断是否在后栅格
				// 0 1 2 3 4
				else if (point_base_link.x < 0 &&
						 fabs(point_base_link.x) - chassis_length / 2.0f >= obs_min_dist &&
						 fabs(point_base_link.y) <= chassis_width / 2.0f)
				{
					grid_index = (int)(obstacle_grid_number / 2 - point_base_link.y / obstacle_grid_size_width);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_backward_current_data_init[grid_index])
					{
						obstacle_laser_backward_current_data_init[grid_index] = 1;
						obstacle_laser_backward_data[grid_index] = fabs(point_base_link.x) - chassis_length / 2.0f;
					}
					else
					{
						obstacle_laser_backward_data[grid_index] = min(obstacle_laser_backward_data[grid_index], fabs(point_base_link.x) - chassis_length / 2.0f);
					}

					obstacle_laser_backward_noupdate_counter[grid_index] = 0;
				}
				// 判断是否在左栅格
				// 0
				// 1
				// 2
				// 3
				// 4
				else if (point_base_link.y > 0 &&
						 fabs(point_base_link.y) - chassis_width / 2.0f >= obs_min_dist &&
						 fabs(point_base_link.x) <= chassis_length / 2.0f)
				{
					grid_index = (int)(obstacle_grid_number / 2 - point_base_link.x / obstacle_grid_size_length);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_left_current_data_init[grid_index])
					{
						obstacle_laser_left_current_data_init[grid_index] = 1;
						obstacle_laser_left_data[grid_index] = fabs(point_base_link.y) - chassis_width / 2.0f;
					}
					else
					{
						obstacle_laser_left_data[grid_index] = min(obstacle_laser_left_data[grid_index], fabs(point_base_link.y) - chassis_width / 2.0f);
					}

					obstacle_laser_left_noupdate_counter[grid_index] = 0;
				}
				// 判断是否在右栅格
				// 4
				// 3
				// 2
				// 1
				// 0
				else if (point_base_link.y < 0 &&
						 fabs(point_base_link.y) - chassis_width / 2.0f >= obs_min_dist &&
						 fabs(point_base_link.x) <= chassis_length / 2.0f)
				{
					grid_index = (int)(point_base_link.x / obstacle_grid_size_length + obstacle_grid_number / 2);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_right_current_data_init[grid_index])
					{
						obstacle_laser_right_current_data_init[grid_index] = 1;
						obstacle_laser_right_data[grid_index] = fabs(point_base_link.y) - chassis_width / 2.0f;
					}
					else
					{
						obstacle_laser_right_data[grid_index] = min(obstacle_laser_right_data[grid_index], fabs(point_base_link.y) - chassis_width / 2.0f);
					}

					obstacle_laser_right_noupdate_counter[grid_index] = 0;
				}
			}
		}

		// 处理雷达障碍物数据强制更新
		for (int i = 0; i < obstacle_grid_number; i++)
		{
			obstacle_laser_forward_noupdate_counter[i]++;
			obstacle_laser_backward_noupdate_counter[i]++;
			obstacle_laser_left_noupdate_counter[i]++;
			obstacle_laser_right_noupdate_counter[i]++;

			obstacle_laser_forward_current_data_init[i] = 0;
			obstacle_laser_backward_current_data_init[i] = 0;
			obstacle_laser_left_current_data_init[i] = 0;
			obstacle_laser_right_current_data_init[i] = 0;

			if (obstacle_laser_forward_noupdate_counter[i] > obstacle_no_update_clear_timeout)
			{
				obstacle_laser_forward_noupdate_counter[i] = 0;
				obstacle_laser_forward_data[i] = INFINITY;
			}

			if (obstacle_laser_backward_noupdate_counter[i] > obstacle_no_update_clear_timeout)
			{
				obstacle_laser_backward_noupdate_counter[i] = 0;
				obstacle_laser_backward_data[i] = INFINITY;
			}

			if (obstacle_laser_left_noupdate_counter[i] > obstacle_no_update_clear_timeout)
			{
				obstacle_laser_left_noupdate_counter[i] = 0;
				obstacle_laser_left_data[i] = INFINITY;
			}

			if (obstacle_laser_right_noupdate_counter[i] > obstacle_no_update_clear_timeout)
			{
				obstacle_laser_right_noupdate_counter[i] = 0;
				obstacle_laser_right_data[i] = INFINITY;
			}
		}

		// 更新障碍物数据
		for (int i = 0; i < obstacle_grid_number; i++)
		{
			// 前
			if (obstacle_laser_forward_data[i] <= obstacle_data.obstacle_forward[i])
			{
				obstacle_data.obstacle_forward[i] = obstacle_laser_forward_data[i];
			}
			else if (obstacle_laser_forward_data[i] < INFINITY)
			{
				obstacle_laser_forward_update_counter[i]++;

				if (obstacle_laser_forward_update_counter[i] >= obstacle_no_update_clear_timeout)
				{
					obstacle_data.obstacle_forward[i] = obstacle_laser_forward_data[i];
					obstacle_laser_forward_update_counter[i] = 0;
				}
			}
			else
			{
				obstacle_data.obstacle_forward[i] = obstacle_laser_forward_data[i];
			}

			// 后
			if (obstacle_laser_backward_data[i] <= obstacle_data.obstacle_backward[i])
			{
				obstacle_data.obstacle_backward[i] = obstacle_laser_backward_data[i];
			}
			else if (obstacle_laser_backward_data[i] < INFINITY)
			{
				obstacle_laser_backward_update_counter[i]++;

				if (obstacle_laser_backward_update_counter[i] >= obstacle_no_update_clear_timeout)
				{
					obstacle_data.obstacle_backward[i] = obstacle_laser_backward_data[i];
					obstacle_laser_backward_update_counter[i] = 0;
				}
			}
			else
			{
				obstacle_data.obstacle_backward[i] = obstacle_laser_backward_data[i];
			}

			// 左
			if (obstacle_laser_left_data[i] <= obstacle_data.obstacle_left[i])
			{
				obstacle_data.obstacle_left[i] = obstacle_laser_left_data[i];
			}
			else if (obstacle_laser_left_data[i] < INFINITY)
			{
				obstacle_laser_left_update_counter[i]++;

				if (obstacle_laser_left_update_counter[i] >= obstacle_no_update_clear_timeout)
				{
					obstacle_data.obstacle_left[i] = obstacle_laser_left_data[i];
					obstacle_laser_left_update_counter[i] = 0;
				}
			}
			else
			{
				obstacle_data.obstacle_left[i] = obstacle_laser_left_data[i];
			}

			// 右
			if (obstacle_laser_right_data[i] <= obstacle_data.obstacle_right[i])
			{
				obstacle_data.obstacle_right[i] = obstacle_laser_right_data[i];
			}
			else if (obstacle_laser_right_data[i] < INFINITY)
			{
				obstacle_laser_right_update_counter[i]++;

				if (obstacle_laser_right_update_counter[i] >= obstacle_no_update_clear_timeout)
				{
					obstacle_data.obstacle_right[i] = obstacle_laser_right_data[i];
					obstacle_laser_right_update_counter[i] = 0;
				}
			}
			else
			{
				obstacle_data.obstacle_right[i] = obstacle_laser_right_data[i];
			}
		}

		// 发布obstacle数据
		obstacle_pub->publish(obstacle_data);

		// 循环频率控制
		loop_rate.sleep();
	}

	// 清理实体后再关闭上下文，避免析构顺序导致的退出崩溃
	laser_scan_sub.reset();
	obstacle_pub.reset();
	node.reset();
	rclcpp::shutdown();
	return 0;
}
