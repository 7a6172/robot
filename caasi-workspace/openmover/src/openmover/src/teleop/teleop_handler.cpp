// 2023-6-21 0.0.0.1A
// ROS 2 Jazzy port (Stage 5): faithful to ROS 1 teleop_handler.
// - joy sub:      openmover/control/joy
// - cmd_vel pub:  openmover/control/cmd_vel_manual (50 Hz, acceleration limited)
// - stop client:  openmover/control/stop/request (openmover_msgs/StopRequest)
// - params:       teleop.* (ROS 1 ~/teleop namespace)

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <sensor_msgs/msg/joy.hpp>
#include <openmover_msgs/srv/stop_request.hpp>

#include <cmath>
#include <memory>

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
geometry_msgs::msg::Twist cmd_vel_data;
geometry_msgs::msg::Twist cmd_vel_target_data;

// 定义上一次进入回调的时间
rclcpp::Time last_callback_time(0, 0, RCL_ROS_TIME);

// 定义紧急制动服务客户端（放在独立节点上，避免与主循环 spin 冲突）
rclcpp::Client<openmover_msgs::srv::StopRequest>::SharedPtr emergency_stop_client;
rclcpp::Node::SharedPtr client_node;

// 定义紧急制动的状态
bool emergency_enable = false;

// 手柄话题回调
void joy_callback(const sensor_msgs::msg::Joy::SharedPtr msg)
{
	static int last_emergency_button_state = 0;

	cmd_vel_target_data.angular.z =
		((fabs(msg->axes[3] - 0.0) > EPS) ? msg->axes[3] : msg->axes[6]) * velocity_yaw;
	cmd_vel_target_data.linear.x =
		((fabs(msg->axes[1] - 0.0) > EPS) ? msg->axes[1] : msg->axes[7]) * velocity_x;

	// 紧急停车
	if (msg->buttons[1] == 1 && last_emergency_button_state == 0)
	{
		auto stop_request = std::make_shared<openmover_msgs::srv::StopRequest::Request>();

		stop_request->enable = !emergency_enable;
		emergency_enable = !emergency_enable;

		auto future = emergency_stop_client->async_send_request(stop_request);

		if (rclcpp::spin_until_future_complete(client_node, future, std::chrono::seconds(5)) !=
			rclcpp::FutureReturnCode::SUCCESS)
		{
			RCLCPP_WARN(rclcpp::get_logger(NODE_NAME), "%s：紧急停车服务调用超时。", TAG);
		}
	}

	last_emergency_button_state = msg->buttons[1];

	last_callback_time = rclcpp::Clock(RCL_ROS_TIME).now();
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
	rclcpp::Rate loop_rate(50);

	// 获取参数（ROS 1 ~/teleop 命名空间）
	velocity_x = node->declare_parameter<float>("teleop.velocity_x", 0.4);
	velocity_yaw = node->declare_parameter<float>("teleop.velocity_yaw", 0.2);
	max_x_acc = node->declare_parameter<float>("teleop.max_x_acc", 1.0);
	max_yaw_acc = node->declare_parameter<float>("teleop.max_yaw_acc", 0.3);

	enable_timeout_protection = node->declare_parameter<bool>("teleop.enable_timeout_protection", false);
	timeout = node->declare_parameter<float>("teleop.timeout", 2.5);

	// 打印调试数据
	RCLCPP_INFO(node->get_logger(), "%s：外部控制参数已获取，最大X轴速度：%.4f 最大Yaw轴速度：%.4f",
				TAG, velocity_x, velocity_yaw);

	// 注册手柄话题监听与回调
	auto joy_sub = node->create_subscription<sensor_msgs::msg::Joy>(
		"openmover/control/joy", 10, joy_callback);

	// 注册底盘控制话题发布器
	auto cmd_vel_pub = node->create_publisher<geometry_msgs::msg::Twist>(
		"openmover/control/cmd_vel_manual", 2);

	// 注册停车服务（独立节点承载客户端）
	client_node = rclcpp::Node::make_shared(std::string(NODE_NAME) + "_client");
	emergency_stop_client = client_node->create_client<openmover_msgs::srv::StopRequest>(
		"openmover/control/stop/request");

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

	last_callback_time = node->now();

	while (rclcpp::ok())
	{
		// 注册回调
		rclcpp::spin_some(node);

		if (enable_timeout_protection &&
			(node->now() - last_callback_time > rclcpp::Duration::from_seconds(timeout)))
		{
			cmd_vel_target_data.linear.x = 0;
			cmd_vel_target_data.angular.z = 0;
		}

		// 线速度加速度控制
		if (fabs(cmd_vel_data.linear.x - cmd_vel_target_data.linear.x) < delta_vx)
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
		if (fabs(cmd_vel_data.angular.z - cmd_vel_target_data.angular.z) < delta_vyaw)
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
		cmd_vel_pub->publish(cmd_vel_data);

		// 循环频率控制
		loop_rate.sleep();
	}

	// 清理实体后再关闭上下文，避免析构顺序导致的退出崩溃
	joy_sub.reset();
	cmd_vel_pub.reset();
	emergency_stop_client.reset();
	client_node.reset();
	node.reset();
	rclcpp::shutdown();
	return 0;
}
