// 2023-11-1 0.0.0.3A

#include <ros/ros.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <sensor_msgs/LaserScan.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/Range.h>
#include <pcl_conversions/pcl_conversions.h>
#include <openmover_msgs/obstacle.h>
#include <geometry_msgs/Polygon.h>
#include <geometry_msgs/Point32.h>
#include <pcl/point_cloud.h>
#include <pcl/common/transforms.h>
#include <tf/tf.h>
#include <tf2_eigen/tf2_eigen.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <linux/input.h>
#include "common/common_state_code.h"
#include "navigation/navigation_state_code.h"
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
geometry_msgs::Polygon footprint_polygon;

// 定义底盘尺寸
float chassis_width = 0.85;
float chassis_length = 0.85;

// 定义网格数
int obstacle_grid_number = 5;

// 定义机器人雷达数据
sensor_msgs::LaserScan laser_scan_data;

// 是否反转雷达 (y 是否取负)
bool ray_reversed = false;

// 定义obstacle发布器
ros::Publisher obstacle_pub;

// 定义obstacle数据
openmover_msgs::obstacle obstacle_data;

// 是否获取到雷达数据标记
bool laser_scan_data_ready = false;

// 定义 tf 组件与变换
unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster;
unique_ptr<tf2_ros::Buffer> tf_buffer;
geometry_msgs::TransformStamped tf_lidar_to_base;
Eigen::Affine3f affine_lidar_to_base;

// laser_scan回调函数
void laser_scan_callback(const sensor_msgs::LaserScan::ConstPtr &msg)
{
	laser_scan_data = *msg;
	laser_scan_data_ready = true;
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
	ros::Rate loop_rate(20);

	// 定义ROS参数获取程序
	ros::NodeHandle node_handle_param("~/obstacle");
	ros::NodeHandle node_handle_param_global("~");

	// 获取参数
	node_handle_param.param<float>("laser_min_dist", laser_min_dist, 0.06);
	node_handle_param.param<float>("laser_max_dist", laser_max_dist, 20);
	node_handle_param.param<float>("obs_min_dist", obs_min_dist, 0.06);

	node_handle_param.param<int>("obstacle_no_update_clear_timeout", obstacle_no_update_clear_timeout, 20);

	// 足迹部分
	XmlRpc::XmlRpcValue footprint_param;
	node_handle_param_global.getParam("footprint", footprint_param);

	for (int i = 0; i < footprint_param.size(); i++)
	{
		vector<float> point_vector;

		for (int j = 0; j < footprint_param[i].size(); j++)
		{
			point_vector.push_back(double(footprint_param[i][j]));
		}

		geometry_msgs::Point32 point;

		point.x = point_vector[0];
		point.y = point_vector[1];

		footprint_polygon.points.push_back(point);
	}

	node_handle_param.param<int>("obstacle_grid_number", obstacle_grid_number, 5);
	node_handle_param.param<bool>("ray_reversed", ray_reversed, false);

	// 初始化 tf 组件
	tf_broadcaster = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster);
	tf_buffer = unique_ptr<tf2_ros::Buffer>(new tf2_ros::Buffer);
	tf2_ros::TransformListener tf_listener(*tf_buffer);

	// 监听雷达到基座的 tf 数据
	tf_lidar_to_base =
		tf_buffer->lookupTransform(LOCALIZATION_BASE_LINK, LOCALIZATION_LIDAR_LINK, ros::Time(0), ros::Duration(60));

	// 雷达到基座的变换
	affine_lidar_to_base = tf2::transformToEigen(tf_lidar_to_base).matrix().cast<float>();

	// 计算底盘尺寸
	chassis_width = abs(footprint_polygon.points[0].y - footprint_polygon.points[1].y);
	chassis_length = abs(footprint_polygon.points[0].x - footprint_polygon.points[3].x);

	ROS_INFO("%s：底盘长度：%f，底盘宽度：%f。", TAG, chassis_length, chassis_width);

	// 定义单个网格尺寸
	float obstacle_grid_size_width = chassis_width / obstacle_grid_number;
	float obstacle_grid_size_length = chassis_length / obstacle_grid_number;

	// 雷达订阅器
	ros::Subscriber laser_scan_sub = node_handle.subscribe("openmover/hardware/lidar/scan/obstacle", 2, laser_scan_callback);

	// obstacle 话题发布器
	obstacle_pub = node_handle.advertise<openmover_msgs::obstacle>("openmover/navigation/obstacle", 1);

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

	while (node_handle.ok())
	{
		// 注册回调
		ros::spinOnce();

		// 初始化obstacle数据
		obstacle_data.header.stamp = ros::Time::now();

		if (laser_scan_data_ready)
		{
			// 枚举 laser_scan
			size_t size = laser_scan_data.ranges.size();

			for (int i = 0; i < size; i++)
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
					abs(point_base_link.x) - chassis_length / 2.0f >= obs_min_dist &&
					abs(point_base_link.y) <= chassis_width / 2.0f)
				{
					grid_index = (int)(point_base_link.y / obstacle_grid_size_width + obstacle_grid_number / 2);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_forward_current_data_init[grid_index])
					{
						obstacle_laser_forward_current_data_init[grid_index] = 1;
						obstacle_laser_forward_data[grid_index] = abs(point_base_link.x) - chassis_length / 2.0f;
					}
					else
					{
						obstacle_laser_forward_data[grid_index] = min(obstacle_laser_forward_data[grid_index], abs(point_base_link.x) - chassis_length / 2.0f);
					}

					obstacle_laser_forward_noupdate_counter[grid_index] = 0;
				}
				// 判断是否在后栅格
				// 0 1 2 3 4
				else if (point_base_link.x < 0 &&
						 abs(point_base_link.x) - chassis_length / 2.0f >= obs_min_dist &&
						 abs(point_base_link.y) <= chassis_width / 2.0f)
				{
					grid_index = (int)(obstacle_grid_number / 2 - point_base_link.y / obstacle_grid_size_width);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_backward_current_data_init[grid_index])
					{
						obstacle_laser_backward_current_data_init[grid_index] = 1;
						obstacle_laser_backward_data[grid_index] = abs(point_base_link.x) - chassis_length / 2.0f;
					}
					else
					{
						obstacle_laser_backward_data[grid_index] = min(obstacle_laser_backward_data[grid_index], abs(point_base_link.x) - chassis_length / 2.0f);
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
						 abs(point_base_link.y) - chassis_width / 2.0f >= obs_min_dist &&
						 abs(point_base_link.x) <= chassis_length / 2.0f)
				{
					grid_index = (int)(obstacle_grid_number / 2 - point_base_link.x / obstacle_grid_size_length);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_left_current_data_init[grid_index])
					{
						obstacle_laser_left_current_data_init[grid_index] = 1;
						obstacle_laser_left_data[grid_index] = abs(point_base_link.y) - chassis_width / 2.0f;
					}
					else
					{
						obstacle_laser_left_data[grid_index] = min(obstacle_laser_left_data[grid_index], abs(point_base_link.y) - chassis_width / 2.0f);
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
						 abs(point_base_link.y) - chassis_width / 2.0f >= obs_min_dist &&
						 abs(point_base_link.x) <= chassis_length / 2.0f)
				{
					grid_index = (int)(point_base_link.x / obstacle_grid_size_length + obstacle_grid_number / 2);
					grid_index = grid_index > obstacle_grid_number - 1 ? obstacle_grid_number - 1 : (grid_index < 0 ? 0 : grid_index);

					// 更新网格数据
					if (!obstacle_laser_right_current_data_init[grid_index])
					{
						obstacle_laser_right_current_data_init[grid_index] = 1;
						obstacle_laser_right_data[grid_index] = abs(point_base_link.y) - chassis_width / 2.0f;
					}
					else
					{
						obstacle_laser_right_data[grid_index] = min(obstacle_laser_right_data[grid_index], abs(point_base_link.y) - chassis_width / 2.0f);
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
		obstacle_pub.publish(obstacle_data);

		// 循环频率控制
		loop_rate.sleep();
	}

	return 0;
}