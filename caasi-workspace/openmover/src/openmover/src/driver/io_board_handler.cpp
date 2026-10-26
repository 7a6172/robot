// ROS 2 port of the ROS 1 io_board_handler node.
// Structure and comments intentionally kept close to the original for comparability.

#include <rclcpp/rclcpp.hpp>
#include <tf2/utils.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>

#include <cmath>
#include <cstring>
#include <thread>
#include <mutex>
#include <limits>

#include <unistd.h>
#include <sys/socket.h>
#include <arpa/inet.h>

#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/int8.hpp>
#include <std_msgs/msg/float32.hpp>
#include <openmover_msgs/msg/obstacle.hpp>
#include <openmover_msgs/msg/bms_data.hpp>
#include <openmover_msgs/msg/nav_to_state.hpp>
#include <common/common_state_code.h>
#include <localization/localization_sources.h>
#include <navigation/navigation_state_code.h>
#include <driver/utils/crc8_maxim.h>

#define NODE_NAME "io_board_handler"
#define TAG "机器人IO板驱动"

using namespace std;

// 通讯定义
#define ROS_STATE_READY 0            // 就绪
#define ROS_STATE_EXECUTING_TASK 1   // 正在执行任务（导航、举升或旋转）
#define ROS_STATE_WAIT_FOR_CONFIRM 2 // 暂停或正在等待交互确认
#define ROS_STATE_BLOCKED 3          // 障碍阻塞
#define ROS_STATE_EMERGENCY 4        // 预留上层紧急状态
#define ROS_STATE_RESETTING 5        // 结束所有任务并尝试恢复定位
#define ROS_STATE_LOW_LOC_CONF 6     // 定位置信度过低
#define ROS_STATE_LOW_BATTERY 7      // 电池电量过低
#define ROS_STATE_EXEC_ERROR 8       // 执行错误
#define ROS_STATE_INIT 9             // 加载中

#define ROS_REQ_LIFT_PLAT_KEEP 0 // 升降平台保持请求
#define ROS_REQ_LIFT_PLAT_UP 1   // 升降平台上升请求
#define ROS_REQ_LIFT_PLAT_DOWN 2 // 升降平台下降请求

#define IO_STATE_BUTTON_RELEASED 0 // 按钮释放
#define IO_STATE_BUTTON_PRESSED 1  // 按钮按下

#define IO_STATE_NOT_IN_EMERGENCY 0 // 非紧急停止
#define IO_STATE_IN_EMERGENCY 1     // 紧急停止

// 定义参数
// 控制频率
float control_freq = 20;

// 连接参数
string ip_address;
int port;

// 版本号
int version_a = 1, version_b = 0, version_c = 0;

// 其它参数
int robot_id = 0;
int low_battery_threshold = 5; // 低电量阈值
int loc_conf_threshold = 45;   // 定位置信度阈值

// 定义TCP
int sock = 0;
struct sockaddr_in serv_addr;

// 定义通讯参数
uint8_t *packet_receive_buffer;

// 定义ROS->IO板报文数据结构
struct ros_to_io_frame_t
{
    // ROS软件版本号：a.b.c
    uint8_t ros_version_a;
    uint8_t ros_version_b;
    uint8_t ros_version_c;
    // 数据段
    uint8_t robot_id = 0;
    uint8_t ros_state = ROS_STATE_READY;
    float pos_x = 0.0f;
    float pos_y = 0.0f;
    float pos_yaw = 0.0f;
    float vx = 0.0f;
    float vyaw = 0.0f;
    uint8_t obs_dist_front = 0; // 0~255cm
    uint8_t obs_dist_back = 0;  // 0~255cm
    uint8_t loc_conf = 0;       // 0-100
    uint8_t crc8 = 0x00;
} __attribute__((packed));

// 定义IO板->ROS报文数据结构
struct io_to_ros_frame_t
{
    // 固件版本号：a.b.c
    uint8_t fw_version_a;
    uint8_t fw_version_b;
    uint8_t fw_version_c;
    // 数据段
    uint8_t button_state = IO_STATE_BUTTON_RELEASED;
    uint8_t emergency_state = IO_STATE_NOT_IN_EMERGENCY;
    uint8_t batt_vol = 0; // 0~25.5，除以 10.0
    uint8_t batt_cur = 0; // 0~25.5，除以 10.0
    uint8_t batt_soc = 0;
    uint8_t crc8 = 0x00;
} __attribute__((packed));

// 定义数据
bool fw_version_received = false;
ros_to_io_frame_t ros_to_io_frame;
io_to_ros_frame_t io_to_ros_frame;
openmover_msgs::msg::BmsData bms_data;
std_msgs::msg::Bool button_data;
std_msgs::msg::Bool reset_state_data;
std_msgs::msg::Bool emergency_data;
geometry_msgs::msg::PoseWithCovarianceStamped pose_data;
geometry_msgs::msg::TwistWithCovarianceStamped twist_data;
openmover_msgs::msg::NavToState nav_to_state_data;
std_msgs::msg::Float32 loc_conf_data;
openmover_msgs::msg::Obstacle obstacle_data;
bool pose_data_received = false;

// 数据锁
mutex data_update_lock;

// 节点指针（供线程内部使用）
rclcpp::Node *node = nullptr;

// 定义发布器
rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr button_state_pub;
rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr emergency_state_pub;
rclcpp::Publisher<openmover_msgs::msg::BmsData>::SharedPtr bms_pub;

// 定义接收器
rclcpp::Subscription<geometry_msgs::msg::TwistWithCovarianceStamped>::SharedPtr twist_sub;
rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr pose_sub;
rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr reset_state_sub;
rclcpp::Subscription<openmover_msgs::msg::NavToState>::SharedPtr nav_to_state_sub;
rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr loc_conf_sub;
rclcpp::Subscription<openmover_msgs::msg::Obstacle>::SharedPtr obstacle_sub;

// 功能函数
bool udp_init()
{
    bool ret = false;

    // 创建套接字
    if ((sock = socket(AF_INET, SOCK_DGRAM, 0)) < 0)
    {
        RCLCPP_ERROR(node->get_logger(), "%s：创建套接字失败。", TAG);

        return ret;
    }

    memset(&serv_addr, '0', sizeof(serv_addr));

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);

    // 将地址从文本转换为二进制
    if (inet_pton(AF_INET, ip_address.c_str(), &serv_addr.sin_addr) <= 0)
    {
        RCLCPP_ERROR(node->get_logger(), "%s：无效地址/地址不支持。", TAG);

        return ret;
    }

    timeval tv_recv{0, 5000};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv));
    timeval tv_send{0, 50000};
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send));

    RCLCPP_INFO(node->get_logger(), "%s：UDP连接成功。", TAG);

    ret = true;

    return ret;
}

// 重置状态控制回调
void reset_state_callback(const std_msgs::msg::Bool::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    reset_state_data = *msg;
}

// 位姿回调
void pose_callback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    pose_data = *msg;

    pose_data_received = true;
}

// 速度回调
void twist_callback(const geometry_msgs::msg::TwistWithCovarianceStamped::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    twist_data = *msg;
}

// 导航状态回调
void nav_to_state_callback(const openmover_msgs::msg::NavToState::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    nav_to_state_data = *msg;
}

// 定位置信度回调
void loc_conf_callback(const std_msgs::msg::Float32::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    loc_conf_data = *msg;
}

// 障碍信息回调
void obstacle_callback(const openmover_msgs::msg::Obstacle::SharedPtr msg)
{
    lock_guard<mutex> lock(data_update_lock);

    obstacle_data = *msg;
}

// 线程函数
void board_communication()
{
    rclcpp::Rate rate(control_freq);

    while (rclcpp::ok())
    {
        // 更新并发送数据
        data_update_lock.lock();

        // 机器人编号
        ros_to_io_frame.robot_id = robot_id;

        // 状态判断
        // 紧急停止
        if (emergency_data.data)
        {
            ros_to_io_frame.ros_state = ROS_STATE_EMERGENCY;
        }
        // 电量判断
        else if (bms_data.soc < low_battery_threshold)
        {
            ros_to_io_frame.ros_state = ROS_STATE_LOW_BATTERY;
        }
        // 正在重置中
        else if (reset_state_data.data)
        {
            ros_to_io_frame.ros_state = ROS_STATE_RESETTING;
        }
        // 定位置信度低
        else if (loc_conf_data.data * 100.0f < loc_conf_threshold)
        {
            ros_to_io_frame.ros_state = ROS_STATE_LOW_LOC_CONF;
        }
        // 导航错误
        else if (nav_to_state_data.state == NAV_STATE_ERROR)
        {
            ros_to_io_frame.ros_state = ROS_STATE_EXEC_ERROR;
        }
        // 导航阻塞
        else if (nav_to_state_data.state == NAV_STATE_BLOCKED)
        {
            ros_to_io_frame.ros_state = ROS_STATE_BLOCKED;
        }
        // 导航暂停/等待确定
        else if (nav_to_state_data.state == NAV_STATE_PAUSE)
        {
            ros_to_io_frame.ros_state = ROS_STATE_WAIT_FOR_CONFIRM;
        }
        // 任务运行中
        else if (nav_to_state_data.state == NAV_STATE_RUNNING)
        {
            ros_to_io_frame.ros_state = ROS_STATE_EXECUTING_TASK;
        }
        else if (pose_data_received)
        {
            ros_to_io_frame.ros_state = ROS_STATE_READY;
        }
        else
        {
            ros_to_io_frame.ros_state = ROS_STATE_INIT;
        }

        // 定位信息
        ros_to_io_frame.pos_x = pose_data.pose.pose.position.x;
        ros_to_io_frame.pos_y = pose_data.pose.pose.position.y;
        ros_to_io_frame.pos_yaw = tf2::getYaw(pose_data.pose.pose.orientation) / M_PI * 180.0f;

        // 速度信息
        ros_to_io_frame.vx = twist_data.twist.twist.linear.x;
        ros_to_io_frame.vyaw = twist_data.twist.twist.angular.z / M_PI * 180.0f;

        // 障碍物距离
        float front_min_obs_dist = numeric_limits<float>::max();
        float rear_min_obs_dist = numeric_limits<float>::max();

        for (const auto &dist : obstacle_data.obstacle_forward)
        {
            if (dist * 100.0f < front_min_obs_dist && dist > 0.0f && isfinite(dist))
            {
                front_min_obs_dist = dist * 100.0f;
            }
        }

        for (const auto &dist : obstacle_data.obstacle_backward)
        {
            if (dist * 100.0f < rear_min_obs_dist && dist > 0.0f && isfinite(dist))
            {
                rear_min_obs_dist = dist * 100.0f;
            }
        }

        ros_to_io_frame.obs_dist_front = (front_min_obs_dist < 255.0f) ? (uint8_t)(front_min_obs_dist + 0.5f) : 255;
        ros_to_io_frame.obs_dist_back = (rear_min_obs_dist < 255.0f) ? (uint8_t)(rear_min_obs_dist + 0.5f) : 255;

        // 定位置信度
        ros_to_io_frame.loc_conf = (loc_conf_data.data * 100.0f > 100.0f) ? 100 : (uint8_t)(loc_conf_data.data * 100.0f + 0.5f);

        // 校验值
        ros_to_io_frame.crc8 = crc8_maxim((uint8_t *)&ros_to_io_frame, sizeof(ros_to_io_frame_t) - 1);

        bool udp_error = false;

        udp_error |= (sendto(sock, (const void *)&ros_to_io_frame, sizeof(ros_to_io_frame_t), 0,
                             (struct sockaddr *)&serv_addr, sizeof(serv_addr)) == -1);

        data_update_lock.unlock();

        // 等待回收数据
        ssize_t total_recv_len = 0;

        if (!udp_error)
        {
            double start_time = node->now().seconds();

            do
            {
                socklen_t addr_len = sizeof(serv_addr);
                ssize_t recv_len = recvfrom(sock, packet_receive_buffer + total_recv_len, sizeof(io_to_ros_frame_t) - total_recv_len, 0,
                                            (struct sockaddr *)&serv_addr, &addr_len);

                if (recv_len > 0)
                {
                    total_recv_len += recv_len;
                }
            } while (total_recv_len < (ssize_t)sizeof(io_to_ros_frame_t) && abs(node->now().seconds() - start_time) < 0.2);
        }

        if (udp_error)
        {
            RCLCPP_ERROR(node->get_logger(), "%s：UDP连接失败，准备重新连接。", TAG);

            // 尝试重连
            udp_init();
        }
        else if (total_recv_len == (ssize_t)sizeof(io_to_ros_frame_t))
        {
            if (packet_receive_buffer[sizeof(io_to_ros_frame_t) - 1] ==
                crc8_maxim(packet_receive_buffer, sizeof(io_to_ros_frame_t) - 1))
            {
                // 解析数据
                memcpy(&io_to_ros_frame, packet_receive_buffer, sizeof(io_to_ros_frame_t));

                // 发布版本号
                if (!fw_version_received)
                {
                    RCLCPP_INFO(node->get_logger(), "%s：固件版本号：%d.%d.%d。",
                                TAG, io_to_ros_frame.fw_version_a, io_to_ros_frame.fw_version_b, io_to_ros_frame.fw_version_c);

                    fw_version_received = true;
                }

                // 更新本地数据
                // 电池数据
                bms_data.header.stamp = node->now();
                bms_data.voltage = io_to_ros_frame.batt_vol / 10.0f;
                bms_data.soc = io_to_ros_frame.batt_soc;
                bms_data.current = io_to_ros_frame.batt_cur / 10.0f;

                // 按钮数据
                button_data.data = (io_to_ros_frame.button_state == IO_STATE_BUTTON_PRESSED) ? true : false;

                // 紧急状态数据
                emergency_data.data = (io_to_ros_frame.emergency_state == IO_STATE_IN_EMERGENCY) ? true : false;

                // 发布数据
                button_state_pub->publish(button_data);
                emergency_state_pub->publish(emergency_data);
                bms_pub->publish(bms_data);
            }
        }

        rate.sleep();
    }
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    rclcpp::init(argc, argv);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 定义ROS节点处理程序
    auto node_handle = rclcpp::Node::make_shared(NODE_NAME);
    node = node_handle.get();

    // 打印调试信息
    RCLCPP_INFO(node_handle->get_logger(), "%s:节点已启动。", TAG);

    // 获取参数（ROS 1: ~/robot/xxx -> ROS 2: robot.xxx）
    control_freq = (float)node_handle->declare_parameter<double>("robot.control_freq", 20.0);

    // The chassis IO board and the motor controller live on the SAME address and differ
    // only by UDP port: motors answer on 23, the IO board on 26. `robot.port` previously
    // defaulted to 23, which meant an omitted or misspelled configuration silently aimed
    // IO traffic at the motor controller -- the one destination this node must never
    // reach. Both the address and the port are now required, and the motor port is
    // rejected outright.
    {
        const auto &ov =
            node_handle->get_node_parameters_interface()->get_parameter_overrides();
        std::vector<std::string> missing, bad;

        auto read_str = [&](const char *key, std::string &out) {
            auto it = ov.find(key);
            if (it == ov.end() ||
                it->second.get_type() == rclcpp::ParameterType::PARAMETER_NOT_SET)
            {
                missing.emplace_back(key);
                return;
            }
            if (it->second.get_type() != rclcpp::ParameterType::PARAMETER_STRING)
            {
                bad.emplace_back(std::string(key) + " must be a string");
                return;
            }
            out = it->second.get<std::string>();
        };
        auto read_int = [&](const char *key, int &out, bool &have) {
            auto it = ov.find(key);
            if (it == ov.end() ||
                it->second.get_type() == rclcpp::ParameterType::PARAMETER_NOT_SET)
            {
                missing.emplace_back(key);
                return;
            }
            if (it->second.get_type() == rclcpp::ParameterType::PARAMETER_INTEGER)
            {
                out = (int)it->second.get<int64_t>();
                have = true;
            }
            else
            {
                bad.emplace_back(std::string(key) + " must be an integer");
            }
        };

        std::string s_ip;
        int i_port = 0;
        bool have_port = false;
        read_str("robot.ip_address", s_ip);
        read_int("robot.port", i_port, have_port);

        if (!bad.empty())
        {
            std::string list;
            for (const auto &b : bad) list += "\n  - " + b;
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s:参数类型无效，拒绝启动。问题:%s", TAG, list.c_str());
            rclcpp::shutdown();
            return 1;
        }
        if (!missing.empty())
        {
            std::string list;
            for (const auto &m : missing) list += "\n  - " + m;
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s:缺少必需参数，拒绝启动（不会用默认值代替）。缺失:%s",
                         TAG, list.c_str());
            rclcpp::shutdown();
            return 1;
        }
        if (i_port < 1 || i_port > 65535)
        {
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s:robot.port=%d 无效（必须在 1..65535）。", TAG, i_port);
            rclcpp::shutdown();
            return 1;
        }
        // Hard refusal: port 23 belongs to the motor controller. Refusing here means a
        // wrong or inherited configuration cannot reach the motor endpoint by accident.
        if (i_port == 23)
        {
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s:robot.port=23 是电机控制器的端口，IO 板必须使用 26。"
                         "拒绝启动以避免向电机端点发送 IO 报文。", TAG);
            rclcpp::shutdown();
            return 1;
        }
        if (s_ip.empty())
        {
            RCLCPP_FATAL(node_handle->get_logger(), "%s:robot.ip_address 不能为空。", TAG);
            rclcpp::shutdown();
            return 1;
        }

        ip_address = s_ip;
        port = i_port;
    }

    version_a = node_handle->declare_parameter<int>("robot.version_a", 1);
    version_b = node_handle->declare_parameter<int>("robot.version_b", 0);
    version_c = node_handle->declare_parameter<int>("robot.version_c", 0);

    robot_id = node_handle->declare_parameter<int>("robot.robot_id", 0);

    low_battery_threshold = node_handle->declare_parameter<int>("robot.low_battery_threshold", 5);
    loc_conf_threshold = node_handle->declare_parameter<int>("robot.loc_conf_threshold", 45);

    // 初始化数据
    bms_data.soc = 100.0f;
    loc_conf_data.data = 1.0f;

    // 初始化系统
    if (udp_init())
    {
        // 初始化订阅器
        twist_sub = node_handle->create_subscription<geometry_msgs::msg::TwistWithCovarianceStamped>(
            "openmover/localization/twist", 10, twist_callback);
        pose_sub = node_handle->create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
            "openmover/localization/pose", 10, pose_callback);
        reset_state_sub = node_handle->create_subscription<std_msgs::msg::Bool>(
            "openmover/control/reset_state", 10, reset_state_callback);
        nav_to_state_sub = node_handle->create_subscription<openmover_msgs::msg::NavToState>(
            "openmover/navigation/state", 10, nav_to_state_callback);
        loc_conf_sub = node_handle->create_subscription<std_msgs::msg::Float32>(
            "openmover/localization/confidence", 10, loc_conf_callback);
        obstacle_sub = node_handle->create_subscription<openmover_msgs::msg::Obstacle>(
            "openmover/navigation/obstacle", 10, obstacle_callback);

        // 初始化发布器（ROS 1 锁存 -> ROS 2 transient_local）
        auto latched_qos = rclcpp::QoS(1).reliable().transient_local();

        button_state_pub = node_handle->create_publisher<std_msgs::msg::Bool>("openmover/hardware/button", latched_qos);
        emergency_state_pub = node_handle->create_publisher<std_msgs::msg::Bool>("openmover/hardware/emergency", latched_qos);
        bms_pub = node_handle->create_publisher<openmover_msgs::msg::BmsData>("openmover/hardware/bms", latched_qos);

        // 定义循环速度控制
        rclcpp::Rate rate(control_freq);

        // 填充数据
        pose_data.header.frame_id = LOCALIZATION_MAP;
        pose_data.header.stamp = node_handle->now();
        tf2::Quaternion init_q;
        init_q.setRPY(0.0, 0.0, 0.0);
        pose_data.pose.pose.orientation = tf2::toMsg(init_q);

        // 初始化数据
        packet_receive_buffer = new uint8_t[sizeof(io_to_ros_frame_t)];
        ros_to_io_frame.ros_version_a = version_a;
        ros_to_io_frame.ros_version_b = version_b;
        ros_to_io_frame.ros_version_c = version_c;
        ros_to_io_frame.ros_state = ROS_STATE_INIT;

        // 启动读取线程
        std::thread commnuication_thread(board_communication);

        RCLCPP_INFO(node_handle->get_logger(), "%s：IO板通讯线程已启动。", TAG);

        rclcpp::executors::SingleThreadedExecutor executor;
        executor.add_node(node_handle);

        while (rclcpp::ok())
        {
            // 处理回调函数
            executor.spin_some();

            // 循环频率控制
            rate.sleep();
        }

        commnuication_thread.join();

        delete[] packet_receive_buffer;
    }

    rclcpp::shutdown();

    return 0;
}
