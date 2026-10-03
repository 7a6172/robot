// 2023-6-21 0.0.0.1A

#include <ros/ros.h>
#include <geometry_msgs/Twist.h>
#include <std_msgs/Int32.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <linux/input.h>
#include <sensor_msgs/Joy.h>
#include <openmover_msgs/stop_request.h>

#define NODE_NAME "teleop_handler"
#define TAG "手动控制"
#define EPS 1e-5

using namespace std;

// 定义节点参数
float velocity_x;
float velocity_yaw;
float max_x_acc;
float max_yaw_acc;
bool enable_timeout_protection;
float timeout;

// 定义速度发布数据
geometry_msgs::Twist cmd_vel_data;
geometry_msgs::Twist cmd_vel_target_data;

// 定义上一次进入回调的时间
ros::Time last_callback_time;

// 定义紧急制动服务客户端
ros::ServiceClient emergency_stop_client;

// 定义紧急制动的状态
bool emergency_enable = false;


// 手柄话题回调
void joy_callback(const sensor_msgs::Joy::ConstPtr &msg)
{
	static int last_emergency_button_state = 0;

	cmd_vel_target_data.angular.z =
		((abs(msg->axes[3] - 0.0) > EPS) ? msg->axes[3] : msg->axes[6]) * velocity_yaw;
	cmd_vel_target_data.linear.x =
		((abs(msg->axes[1] - 0.0) > EPS) ? msg->axes[1] : msg->axes[7]) * velocity_x;

	// 紧急停车
	if (msg->buttons[1] == 1 && last_emergency_button_state == 0)
	{
		openmover_msgs::stop_request stop_request;
		
		stop_request.request.enable = !emergency_enable;
		emergency_enable = !emergency_enable;

		emergency_stop_client.call(stop_request);
	}

	last_emergency_button_state = msg->buttons[1];

	last_callback_time = ros::Time::now();
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
	ros::Rate loop_rate(50);

	// 定义ROS参数获取程序
	ros::NodeHandle node_handle_param("~/teleop");

	// 获取参数
	node_handle_param.param<float>("velocity_x", velocity_x, 0.4);
	node_handle_param.param<float>("velocity_yaw", velocity_yaw, 0.2);
	node_handle_param.param<float>("max_x_acc", max_x_acc, 1);
	node_handle_param.param<float>("max_yaw_acc", max_yaw_acc, 0.3);

	node_handle_param.param<bool>("enable_timeout_protection", enable_timeout_protection, false);
	node_handle_param.param<float>("timeout", timeout, 2.5);

	// 打印调试数据
	ROS_INFO("%s：外部控制参数已获取，最大X轴速度：%.4lf 最大Yaw轴速度：%.4lf",
			 TAG, velocity_x, velocity_yaw);

	// 注册手柄话题监听与回调
	ros::Subscriber joy_sub = node_handle.subscribe("openmover/control/joy", 10, &joy_callback);

	// 注册底盘控制话题发布器
	ros::Publisher cmd_vel_pub = node_handle.advertise<geometry_msgs::Twist>("openmover/control/cmd_vel_manual", 2);

	// 注册停车服务
	emergency_stop_client = node_handle.serviceClient<openmover_msgs::stop_request>("openmover/control/stop/request");

	// 初始化速度发布数据
	cmd_vel_data.linear.x = 0;
	cmd_vel_data.linear.y = 0;
	cmd_vel_data.linear.z = 0;
	cmd_vel_data.angular.x = 0;
	cmd_vel_data.angular.y = 0;
	cmd_vel_data.angular.z = 0;

	cmd_vel_target_data.linear.x = 0;
	cmd_vel_target_data.linear.y = 0;
	cmd_vel_target_data.linear.z = 0;
	cmd_vel_target_data.angular.x = 0;
	cmd_vel_target_data.angular.y = 0;
	cmd_vel_target_data.angular.z = 0;

	// 计算每一次加速度变化
	double delta_vx = max_x_acc / 50.0;
	double delta_vyaw = max_yaw_acc / 50.0;

	last_callback_time = ros::Time::now();

	while (node_handle.ok())
	{
		// 注册回调
		ros::spinOnce();

		if (enable_timeout_protection && (ros::Time::now() - last_callback_time > ros::Duration(timeout)))
		{
			cmd_vel_target_data.linear.x = 0;
			cmd_vel_target_data.angular.z = 0;
		}

		// 线速度加速度控制
		if (abs(cmd_vel_data.linear.x - cmd_vel_target_data.linear.x) < delta_vx)
		{
			cmd_vel_data.linear.x = cmd_vel_target_data.linear.x;
		}
		else if (cmd_vel_data.linear.x < cmd_vel_target_data.linear.x)
		{
			cmd_vel_data.linear.x += delta_vx;
		}
		else if (cmd_vel_data.linear.x > cmd_vel_target_data.linear.x)
		{
			cmd_vel_data.linear.x -= delta_vx;
		}

		// 角速度加速度控制
		if (abs(cmd_vel_data.angular.z - cmd_vel_target_data.angular.z) < delta_vyaw)
		{
			cmd_vel_data.angular.z = cmd_vel_target_data.angular.z;
		}
		else if (cmd_vel_data.angular.z < cmd_vel_target_data.angular.z)
		{
			cmd_vel_data.angular.z += delta_vyaw;
		}
		else if (cmd_vel_data.angular.z > cmd_vel_target_data.angular.z)
		{
			cmd_vel_data.angular.z -= delta_vyaw;
		}

		// 发布速度话题数据
		cmd_vel_pub.publish(cmd_vel_data);

		// 循环频率控制
		loop_rate.sleep();
	}

	return 0;
}
