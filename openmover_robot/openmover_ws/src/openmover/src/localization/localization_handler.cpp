// 2023-6-24 0.0.0.1A

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
#include <linux/input.h>
#include <angles/angles.h>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"

#define NODE_NAME "localization_handler"
#define TAG "全局定位管理"

using namespace std;

// 定义里程计发布器
ros::Publisher odom_pub;
ros::Publisher odom_legacy_pub;

// 定义里程计速度发布器
ros::Publisher odom_twist_pub;

// 定义里程计数据
geometry_msgs::PoseWithCovarianceStamped odom_data;
nav_msgs::Odometry odom_legacy_data;
bool odom_received = false;

// 定义里程计速度数据
geometry_msgs::TwistWithCovarianceStamped twist_data;

// 定义全局位姿数据
geometry_msgs::PoseWithCovarianceStamped pose_data;

// 定义直接输出位姿数据
geometry_msgs::PoseWithCovarianceStamped pose_aft_mapped_data;

// 定义 tf 变换数据
geometry_msgs::TransformStamped map_to_base_trans;
geometry_msgs::TransformStamped odom_trans;

// 定义位姿差值
double odom_diff_x = 0;
double odom_diff_y = 0;
double odom_diff_z = 0;
double odom_diff_yaw = 0;

// 定义初始差值
double init_diff_x = 0;
double init_diff_y = 0;
double init_diff_z = 0;
double init_diff_yaw = 0;

// 定义初始位姿控制变量
bool init_pose_set_request_received = false;
geometry_msgs::PoseWithCovarianceStamped init_pose;
ros::Time init_pose_request_received_time;

// tf发布器
unique_ptr<tf2_ros::TransformBroadcaster> tf_odom_to_base_footprint;

// pose 发布时间记录
ros::Time last_odom_tf_publish_time;

// 定位直接输出模式标记
bool direct_output = false;

// 里程计回调函数
void odom_callback(const geometry_msgs::PoseWithCovarianceStamped::ConstPtr &msg)
{
	// 发布里程计数据
	odom_data.header = msg->header;
	odom_data.pose = msg->pose;

	double x = odom_data.pose.pose.position.x - odom_diff_x;
	double y = odom_data.pose.pose.position.y - odom_diff_y;
	odom_data.pose.pose.position.x = x * cos(odom_diff_yaw) + y * sin(odom_diff_yaw);
	odom_data.pose.pose.position.y = y * cos(odom_diff_yaw) - x * sin(odom_diff_yaw);

	odom_data.pose.pose.position.z -= odom_diff_z;
	odom_data.pose.pose.orientation = tf::createQuaternionMsgFromYaw(
		angles::normalize_angle(tf::getYaw(odom_data.pose.pose.orientation) - odom_diff_yaw));

	odom_pub.publish(odom_data);

	odom_legacy_data.header = odom_data.header;
	odom_legacy_data.child_frame_id = LOCALIZATION_BASE_LINK;
	odom_legacy_data.pose = odom_data.pose;
	odom_legacy_data.twist = twist_data.twist;

	odom_legacy_pub.publish(odom_legacy_data);

	// 发布里程计tf变换
	if (odom_data.header.stamp != last_odom_tf_publish_time)
	{
		odom_trans.header = odom_data.header;
		odom_trans.child_frame_id = LOCALIZATION_BASE_LINK;

		if (abs(twist_data.twist.twist.linear.x) > 1e-4 ||
			abs(twist_data.twist.twist.angular.z) > 1e-4 ||
			!odom_received)
		{
			odom_trans.transform.translation.x = odom_data.pose.pose.position.x;
			odom_trans.transform.translation.y = odom_data.pose.pose.position.y;
			odom_trans.transform.rotation = odom_data.pose.pose.orientation;
		}

		// 直接输出模式由定位算法管理全局 TF
		if (!direct_output)
		{
			try
			{
				tf_odom_to_base_footprint->sendTransform(odom_trans);
			}
			catch (...)
			{
				ROS_WARN("%s：无法发送变换。", TAG);
			}
		}

		last_odom_tf_publish_time = odom_data.header.stamp;
	}

	// 标记收到里程计数据
	odom_received = true;
}

// 速度回调函数
void twist_callback(const geometry_msgs::TwistWithCovarianceStamped::ConstPtr &msg)
{
	// 发布里程计速度数据
	twist_data.header = msg->header;
	twist_data.twist = msg->twist;

	odom_twist_pub.publish(twist_data);
}

// 全局位姿回调函数
void pose_aft_mapped_callback(const geometry_msgs::PoseWithCovarianceStamped::ConstPtr &msg)
{
	pose_data.pose.covariance = msg->pose.covariance;
	pose_aft_mapped_data = *msg;
}

bool init_pose_request_callback(relocalization_toolbox_msgs::initial_pose_request::Request &req, relocalization_toolbox_msgs::initial_pose_request::Response &res)
{
	bool ret = false;

	try
	{
		// 判断是否存在话题
		auto odom_msg = ros::topic::waitForMessage<geometry_msgs::PoseWithCovarianceStamped>("openmover/hardware/odom", ros::Duration(2.0));

		// 等待获取若干次话题，排除缓存影响
		if (odom_msg)
		{
			for (int i = 0; i < 5; i++)
			{
				odom_msg = ros::topic::waitForMessage<geometry_msgs::PoseWithCovarianceStamped>("openmover/hardware/odom", ros::Duration(2.0));

				ros::Duration(0.2).sleep();
			}
		}

		if (odom_msg)
		{
			// ROS_INFO("%lf %lf %lf", odom_msg->pose.pose.position.x, odom_msg->pose.pose.position.y, tf::getYaw(odom_msg->pose.pose.orientation));

			// 设置里程计初始值
			odom_diff_yaw = tf::getYaw(odom_msg->pose.pose.orientation) - tf::getYaw(req.pose.pose.pose.orientation);
			double x = req.pose.pose.pose.position.x;
			double y = req.pose.pose.pose.position.y;
			odom_diff_x = odom_msg->pose.pose.position.x - (x * cos(odom_diff_yaw) - y * sin(odom_diff_yaw));
			odom_diff_y = odom_msg->pose.pose.position.y - (y * cos(odom_diff_yaw) + x * sin(odom_diff_yaw));
			odom_diff_z = odom_msg->pose.pose.position.z - req.pose.pose.pose.position.z;

			// 设置已获取到设置初始位姿请求
			init_pose_set_request_received = true;
			init_pose = req.pose;
			init_pose_request_received_time = ros::Time::now();
			odom_received = false;

			res.result = CMD_RESPONSE_OK;
		}
		else
		{
			res.result = CMD_RESPONSE_ERROR;
		}
	}
	catch (...)
	{
		res.result = CMD_RESPONSE_ERROR;
	}

	ret = true;

	return ret;
}

bool direct_request_callback(openmover_msgs::direct_request::Request &req, openmover_msgs::direct_request::Response &res)
{
	bool ret = false;

	direct_output = req.direct;

	if (direct_output)
	{
		ROS_INFO("%s：定位管理切换为直接输出模式。", TAG);
	}
	else
	{
		ROS_INFO("%s：定位管理切换为传统模式。", TAG);
	}

	res.result = CMD_RESPONSE_OK;

	ret = true;

	return ret;
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
	ros::Rate loop_rate(200);

	// 定义ROS参数获取程序
	ros::NodeHandle node_handle_param("~");

	// 获取参数
	node_handle_param.param<double>("init_diff_x", init_diff_x, 0);
	node_handle_param.param<double>("init_diff_y", init_diff_y, 0);
	node_handle_param.param<double>("init_diff_z", init_diff_z, 0);
	node_handle_param.param<double>("init_diff_yaw", init_diff_yaw, 0);

	odom_diff_x = init_diff_x;
	odom_diff_y = init_diff_y;
	odom_diff_z = init_diff_z;
	odom_diff_yaw = init_diff_yaw;

	// 里程计与速度订阅器
	ros::Subscriber odom_sub = node_handle.subscribe("openmover/hardware/odom", 4, odom_callback);
	ros::Subscriber twist_sub = node_handle.subscribe("openmover/hardware/twist", 4, twist_callback);

	// 里程计话题发布器
	odom_pub = node_handle.advertise<geometry_msgs::PoseWithCovarianceStamped>("openmover/localization/odom", 2);
	odom_legacy_pub = node_handle.advertise<nav_msgs::Odometry>("openmover/localization/odom_legacy", 2);

	// 里程计速度话题发布器
	odom_twist_pub = node_handle.advertise<geometry_msgs::TwistWithCovarianceStamped>("openmover/localization/twist", 2);

	// 全局位姿订阅器
	ros::Subscriber pose_sub = node_handle.subscribe("openmover/localization/pose_aft_mapped", 4, pose_aft_mapped_callback);

	// 全局位姿话题发布器
	ros::Publisher pose_pub = node_handle.advertise<geometry_msgs::PoseWithCovarianceStamped>("openmover/localization/pose", 2);

	// 重置位姿话题发布器
	ros::Publisher init_pose_pub = node_handle.advertise<geometry_msgs::PoseWithCovarianceStamped>("openmover/localization/initialpose", 1);

	// init_pose_request 服务订阅器
	ros::ServiceServer init_pose_request_server = node_handle.advertiseService("openmover/localization/initialpose/request", init_pose_request_callback);

	// direct_request 服务订阅器
	ros::ServiceServer direct_request_server = node_handle.advertiseService("openmover/localization/direct/request", direct_request_callback);

	// tf监听器
	tf2_ros::Buffer tf_buffer;
	tf2_ros::TransformListener tf_listener(tf_buffer);

	// odom tf 发布器
	tf_odom_to_base_footprint = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster());

	// 初始化数据
	pose_data.header.frame_id = LOCALIZATION_MAP;
	last_odom_tf_publish_time = ros::Time::now();
	pose_data.pose.pose.orientation = tf::createQuaternionMsgFromYaw(0);
	odom_data.pose.pose.orientation = tf::createQuaternionMsgFromYaw(0);

	while (node_handle.ok())
	{
		// 注册回调
		ros::spinOnce();

		// 获取机器人全局位姿
		try
		{
			if (direct_output)
			{
				pose_data = pose_aft_mapped_data;
			}
			else
			{
				map_to_base_trans = tf_buffer.lookupTransform(LOCALIZATION_MAP, LOCALIZATION_BASE_LINK, ros::Time(0), ros::Duration(0.2));

				pose_data.header = map_to_base_trans.header;
				pose_data.pose.pose.position.x = map_to_base_trans.transform.translation.x;
				pose_data.pose.pose.position.y = map_to_base_trans.transform.translation.y;
				pose_data.pose.pose.position.z = map_to_base_trans.transform.translation.z;
				pose_data.pose.pose.orientation = map_to_base_trans.transform.rotation;
			}

			pose_pub.publish(pose_data);

			if (init_pose_set_request_received && ros::Time::now() - init_pose_request_received_time >= ros::Duration(1.0))
			{
				init_pose_set_request_received = false;
				init_pose.header.stamp = ros::Time::now();
				init_pose_pub.publish(init_pose);
			}
		}
		catch (...)
		{
			// ROS_WARN("%s：未获取全局位姿。", TAG);
		};

		// 循环频率控制
		loop_rate.sleep();
	}

	if (tf_odom_to_base_footprint != NULL)
	{
		tf_odom_to_base_footprint.reset();
	}

	return 0;
}