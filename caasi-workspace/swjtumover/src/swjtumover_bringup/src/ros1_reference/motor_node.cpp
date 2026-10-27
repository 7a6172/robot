#include <ros/ros.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <chrono>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <limits>
#include <thread>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <tf/tf.h>
#include <boost/thread.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <geometry_msgs/Twist.h>
#include <nav_msgs/Odometry.h>
#include <netinet/tcp.h>
#include <angles/angles.h>
#include <robot_frames.h>
#include <utils/crc8_maxim.h>
#include <utils/motor_safety.h>
#include <swjtumover_msgs/motor_state.h>

#define NODE_NAME "motor_node"
#define TAG "机器人电机驱动"

using namespace std;

// 通讯定义
#define STATE_CONTROL_LEFT_MOTOR 0
#define STATE_CONTROL_RIGHT_MOTOR 1
#define MOTOR_LEFT_ID 1
#define MOTOR_RIGHT_ID 2
#define MOTOR_CMD_BUFFER_SIZE 10
#define MOTOR_RECV_BUFFER_SIZE 10

// 定义参数
// 控制频率
float control_freq = 50;

// 连接参数
string ip_address;
int port;

// 电机参数
int wheel_max_speed_rpm = 300;
int wheel_acc = 1000;
double cmd_vel_timeout = 0.5;
double motor_feedback_timeout = 0.5;
motor_safety::Guard motor_guard;
int16_t last_sent_left_rpm = 0;
int16_t last_sent_right_rpm = 0;

double steady_seconds()
{
    return chrono::duration<double>(chrono::steady_clock::now().time_since_epoch()).count();
}

// 底盘参数
double chassis_radius = 0;
double wheel_radius = 0;
double odom_compensation_ratio = 1;

// 是否发布里程计tf参数
bool publish_tf;

// 定义UDP
int sock = -1;
struct sockaddr_in serv_addr;

// 定义通讯相关
uint8_t comm_state = STATE_CONTROL_LEFT_MOTOR;
uint8_t packet_receive_buffer[MOTOR_RECV_BUFFER_SIZE] = {0x00};
uint8_t packet_send_buffer[MOTOR_CMD_BUFFER_SIZE] = {0x00};

// 定义电机数据结构
struct motor_speed_cmd_data_t
{
    int16_t speed_rpm_left;
    int16_t speed_rpm_right;
} motor_speed_cmd_data;

struct motor_data_t
{
    ros::Time header_stamp;
    float phase_current_left;
    float phase_current_right;
    int16_t speed_rpm_left;
    int16_t speed_rpm_right;
    float position_deg_left;
    float position_deg_right;
    uint8_t error_code_left;
    uint8_t error_code_right;
} motor_data, last_motor_data;

// 定义航迹推算数据
struct odom_data_t
{
    double x;
    double y;
    double yaw;
    double vx;
    double vyaw;
} odom_data_raw;

nav_msgs::Odometry odom_data;
swjtumover_msgs::motor_state motor_left_state_data;
swjtumover_msgs::motor_state motor_right_state_data;

// 定义电机就绪标志
bool motor_ready = false;
bool left_feedback_pending = false;

// 定义发布器
ros::Publisher odom_pub;
ros::Publisher motor_left_state_pub;
ros::Publisher motor_right_state_pub;

// 定义接收器
ros::Subscriber cmd_vel_sub;

// tf发布器
unique_ptr<tf2_ros::TransformBroadcaster> tf_odom_to_base_footprint;

// pose 发布时间记录
ros::Time last_odom_tf_publish_time;

// 定义 tf 变换数据
geometry_msgs::TransformStamped odom_trans;

// 功能函数
bool udp_init()
{
    bool ret = false;

    if (sock >= 0)
    {
        close(sock);
        sock = -1;
    }

    // 创建套接字
    if ((sock = socket(AF_INET, SOCK_DGRAM, 0)) < 0)
    {
        ROS_ERROR("%s：创建套接字失败。", TAG);

        return ret;
    }

    memset(&serv_addr, 0, sizeof(serv_addr));

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);

    // 将地址从文本转换为二进制
    if (inet_pton(AF_INET, ip_address.c_str(), &serv_addr.sin_addr) <= 0)
    {
        ROS_ERROR("%s：无效地址/地址不支持。", TAG);
        close(sock);
        sock = -1;
        return ret;
    }

    timeval tv_recv{0, 5000};
    timeval tv_send{0, 10000};
    if (setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv)) != 0 ||
        setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send)) != 0)
    {
        ROS_ERROR("%s：无法设置 UDP 超时: %s", TAG, strerror(errno));
        close(sock);
        sock = -1;
        return false;
    }

    ROS_INFO("%s：UDP套接字已创建，等待电机有效反馈。", TAG);

    ret = true;

    return ret;
}

// 回调函数
// 速度控制回调
void cmd_vel_callback(const geometry_msgs::Twist::ConstPtr &msg)
{
    if (!std::isfinite(msg->linear.x) || !std::isfinite(msg->angular.z))
    {
        motor_speed_cmd_data.speed_rpm_left = 0;
        motor_speed_cmd_data.speed_rpm_right = 0;
        motor_guard.invalidate_command();
        ROS_ERROR_THROTTLE(1.0, "%s：速度含无效数值，输出零速度。", TAG);
        return;
    }
    // 计算由角速度产生的线速度
    double line_speed = msg->angular.z * chassis_radius;

    // 计算车轮速度
    double speed_left = msg->linear.x - line_speed;
    double speed_right = msg->linear.x + line_speed;

    // 解算为电机 RPM
    const double rpm_scale = 60.0 / (2.0 * M_PI * wheel_radius);
    const double left_rpm = speed_left * rpm_scale;
    const double right_rpm = speed_right * rpm_scale;
    if (!std::isfinite(left_rpm) || !std::isfinite(right_rpm))
    {
        motor_speed_cmd_data.speed_rpm_left = 0;
        motor_speed_cmd_data.speed_rpm_right = 0;
        motor_guard.invalidate_command();
        ROS_ERROR_THROTTLE(1.0, "%s：转速计算溢出，输出零速度。", TAG);
        return;
    }

    // 先限幅再转为 int16_t，避免转换前已经溢出。
    const double limit = wheel_max_speed_rpm;
    motor_speed_cmd_data.speed_rpm_left = static_cast<int16_t>(std::clamp(left_rpm, -limit, limit));
    motor_speed_cmd_data.speed_rpm_right = static_cast<int16_t>(std::clamp(right_rpm, -limit, limit));
    motor_guard.command_received(steady_seconds());
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
    ros::NodeHandle node_handle_param("~/motor");

    // 获取参数
    node_handle_param.param<float>("control_freq", control_freq, 50);

    node_handle_param.param<string>("ip_address", ip_address, "192.168.100.100");
    node_handle_param.param<int>("port", port, 23);

    node_handle_param.param<int>("wheel_max_speed_rpm", wheel_max_speed_rpm, 300);
    node_handle_param.param<int>("wheel_acc", wheel_acc, 10000);
    node_handle_param.param<double>("cmd_vel_timeout", cmd_vel_timeout, 0.5);
    node_handle_param.param<double>("motor_feedback_timeout", motor_feedback_timeout, 0.5);

    node_handle_param.param<double>("chassis_radius", chassis_radius, 0.103);
    node_handle_param.param<double>("wheel_radius", wheel_radius, 0.0535);
    node_handle_param.param<double>("odom_compensation_ratio", odom_compensation_ratio, 1.0);

    node_handle_param.param<bool>("publish_tf", publish_tf, true);

    if (!std::isfinite(control_freq) || control_freq <= 0 ||
        !std::isfinite(cmd_vel_timeout) || cmd_vel_timeout <= 0 ||
        !std::isfinite(motor_feedback_timeout) || motor_feedback_timeout <= 0 ||
        !std::isfinite(chassis_radius) || chassis_radius <= 0 ||
        !std::isfinite(wheel_radius) || wheel_radius <= 0 ||
        !std::isfinite(odom_compensation_ratio) || odom_compensation_ratio <= 0 ||
        wheel_acc <= 0 || wheel_max_speed_rpm <= 0 ||
        wheel_max_speed_rpm > std::numeric_limits<int16_t>::max() || port <= 0 || port > 65535)
    {
        ROS_FATAL("%s：电机参数无效，拒绝启动。", TAG);
        return 1;
    }
    motor_guard = motor_safety::Guard(cmd_vel_timeout, motor_feedback_timeout, steady_seconds());

    // 初始化系统
    if (udp_init())
    {
        // 初始化订阅器
        cmd_vel_sub = node_handle.subscribe<geometry_msgs::Twist>("cmd_vel", 1, cmd_vel_callback);

        // 初始化发布器
        odom_pub = node_handle.advertise<nav_msgs::Odometry>("odom", 1);
        motor_left_state_pub = node_handle.advertise<swjtumover_msgs::motor_state>("motor_state/left", 1);
        motor_right_state_pub = node_handle.advertise<swjtumover_msgs::motor_state>("motor_state/right", 1);

        // tf监听器
        tf2_ros::Buffer tf_buffer;
        tf2_ros::TransformListener tf_listener(tf_buffer);

        // odom tf 发布器
        tf_odom_to_base_footprint = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster());

        // 初始化数据
        odom_data.header.frame_id = LOCALIZATION_ODOM;
        odom_data.child_frame_id = LOCALIZATION_BASE_LINK;
        odom_data.pose.pose.orientation = tf::createQuaternionMsgFromYaw(0);
        motor_guard = motor_safety::Guard(cmd_vel_timeout, motor_feedback_timeout, steady_seconds());

        // 定义循环速度控制
        auto rate = ros::WallRate(control_freq * 2);

        while (node_handle.ok())
        {
            // 处理回调函数
            ros::spinOnce();

            const double wall_now = steady_seconds();
            const bool was_faulted = motor_guard.fault_latched();
            motor_guard.check_feedback(wall_now);
            if (motor_guard.fault_latched())
            {
                if (!was_faulted)
                {
                    motor_ready = false;
                    left_feedback_pending = false;
                }
                ROS_ERROR_THROTTLE(2.0,
                    "%s：电机反馈超时，已锁定零速度；左反馈间隔 %.3fs，右反馈间隔 %.3fs。修复通信后需重启节点。",
                    TAG, motor_guard.feedback_age(0, wall_now), motor_guard.feedback_age(1, wall_now));
            }
            else if (!motor_guard.command_fresh(wall_now) &&
                     (motor_speed_cmd_data.speed_rpm_left != 0 || motor_speed_cmd_data.speed_rpm_right != 0))
            {
                ROS_WARN_THROTTLE(1.0, "%s：cmd_vel 超时，输出零速度。", TAG);
            }

            // 组装发送数据
            packet_send_buffer[0] = comm_state == STATE_CONTROL_LEFT_MOTOR ? MOTOR_LEFT_ID : MOTOR_RIGHT_ID;
            packet_send_buffer[1] = 0x64;

            int16_t speed_rpm = comm_state == STATE_CONTROL_LEFT_MOTOR ? motor_speed_cmd_data.speed_rpm_left : -motor_speed_cmd_data.speed_rpm_right;
            if (!motor_guard.allow_motion(wall_now))
                speed_rpm = 0;
            packet_send_buffer[2] = (uint8_t)(speed_rpm >> 8);
            packet_send_buffer[3] = (uint8_t)(speed_rpm & 0xff);

            packet_send_buffer[4] = 0x00;
            packet_send_buffer[5] = 0x00;

            float time_per_rpm = 1.0f / wheel_acc;
            uint8_t acc_param = static_cast<uint8_t>(min(255.0f, time_per_rpm * 10000.0f + 0.5f));
            packet_send_buffer[6] = acc_param;

            packet_send_buffer[7] = 0x00;

            // 电磁制动
            // if (comm_state == STATE_CONTROL_LEFT_MOTOR)
            // {
            //     if (motor_speed_cmd_data.speed_rpm_left == 0 && abs(motor_data.speed_rpm_left) < 2)
            //     {
            //         packet_send_buffer[7] = 0xff;
            //     }
            // }
            // else
            // {
            //     if (motor_speed_cmd_data.speed_rpm_right == 0 && abs(motor_data.speed_rpm_right) < 2)
            //     {
            //         packet_send_buffer[7] = 0xff;
            //     }
            // }

            packet_send_buffer[8] = 0;

            packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);

            // 发送数据
            bool udp_error = false;

            // 发送数据
            udp_error = (sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
                               (struct sockaddr *)&serv_addr, sizeof(serv_addr)) != MOTOR_CMD_BUFFER_SIZE);
            if (!udp_error)
            {
                if (comm_state == STATE_CONTROL_LEFT_MOTOR)
                    last_sent_left_rpm = speed_rpm;
                else
                    last_sent_right_rpm = speed_rpm;
            }

            // 等待回收数据
            ssize_t total_recv_len = 0;

            if (!udp_error)
            {
                const double deadline = steady_seconds() + 0.01;

                do
                {
                    // 接收地址独立保存，绝不能让回包改写发送目标 serv_addr。
                    sockaddr_in reply_addr{};
                    socklen_t addr_len = sizeof(reply_addr);
                    uint8_t datagram[MOTOR_RECV_BUFFER_SIZE + 1] = {};
                    const ssize_t recv_len = recvfrom(sock, datagram, sizeof(datagram), 0,
                        reinterpret_cast<sockaddr *>(&reply_addr), &addr_len);
                    if (recv_len < 0)
                    {
                        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
                            continue;
                        ROS_WARN_THROTTLE(1.0, "%s：接收电机反馈失败: %s", TAG, strerror(errno));
                        break;
                    }
                    // UDP 每个数据报独立校验，不把几个短包拼成一个反馈包。
                    if (recv_len != MOTOR_RECV_BUFFER_SIZE ||
                        reply_addr.sin_family != AF_INET ||
                        reply_addr.sin_addr.s_addr != serv_addr.sin_addr.s_addr ||
                        datagram[0] != packet_send_buffer[0] ||
                        crc8_maxim(datagram, MOTOR_RECV_BUFFER_SIZE - 1) != datagram[MOTOR_RECV_BUFFER_SIZE - 1])
                    {
                        ROS_WARN_THROTTLE(1.0,
                            "%s：忽略无效电机反馈，长度=%ld，ID=%u，当前请求ID=%u；检查回包来源、长度和CRC。",
                            TAG, static_cast<long>(recv_len), static_cast<unsigned>(datagram[0]),
                            static_cast<unsigned>(packet_send_buffer[0]));
                        continue;
                    }

                    std::copy(datagram, datagram + MOTOR_RECV_BUFFER_SIZE, packet_receive_buffer);
                    total_recv_len = MOTOR_RECV_BUFFER_SIZE;
                    break;
                } while (node_handle.ok() && steady_seconds() < deadline);
            }

            if (udp_error)
            {
                ROS_ERROR_THROTTLE(1.0, "%s：UDP发送失败，已锁定零速度，准备重新创建套接字。", TAG);
                motor_guard.latch_fault();
                motor_ready = false;
                left_feedback_pending = false;

                // 尝试重连
                udp_init();
            }
            else if (total_recv_len == MOTOR_RECV_BUFFER_SIZE)
            {
                motor_data.header_stamp = ros::Time::now();

                if (crc8_maxim(packet_receive_buffer, MOTOR_RECV_BUFFER_SIZE - 1) == packet_receive_buffer[MOTOR_RECV_BUFFER_SIZE - 1])
                {
                    motor_guard.feedback_received(comm_state, steady_seconds());
                    int16_t phase_current_recv = ((int16_t)packet_receive_buffer[2] << 8) | packet_receive_buffer[3];
                    int16_t speed_rpm_recv = ((int16_t)packet_receive_buffer[4] << 8) | packet_receive_buffer[5];
                    uint16_t position_deg_recv = ((uint16_t)packet_receive_buffer[6] << 8) | packet_receive_buffer[7];
                    uint8_t error_code_recv = packet_receive_buffer[8];

                    if (comm_state == STATE_CONTROL_LEFT_MOTOR && packet_receive_buffer[0] == MOTOR_LEFT_ID)
                    {
                        motor_data.phase_current_left = abs(((float)phase_current_recv / 32767.0f) * 8.0f);
                        motor_data.speed_rpm_left = speed_rpm_recv;
                        motor_data.position_deg_left = (float)position_deg_recv * 360.0f / 32767.0f;
                        motor_data.error_code_left = error_code_recv;

                        left_feedback_pending = true;
                    }
                    else if (comm_state == STATE_CONTROL_RIGHT_MOTOR && packet_receive_buffer[0] == MOTOR_RIGHT_ID)
                    {
                        motor_data.phase_current_right = abs(((float)phase_current_recv / 32767.0f) * 8.0f);
                        motor_data.speed_rpm_right = -speed_rpm_recv;
                        motor_data.position_deg_right = 360.0f - ((float)position_deg_recv * 360.0f / 32767.0f);
                        motor_data.error_code_right = error_code_recv;

                        // 只有本轮左、右有效反馈齐全时才更新里程计。
                        // 不能在一侧掉线后用旧位置伪造新的 odom/TF。
                        if (left_feedback_pending && motor_guard.feedback_fresh(steady_seconds()))
                        {
                            if (!motor_ready)
                            {
                                last_motor_data = motor_data;

                                motor_ready = true;
                            }
                            else
                            {
                                // 更新电机状态
                                motor_left_state_data.header.stamp = motor_data.header_stamp;
                                motor_right_state_data.header = motor_left_state_data.header;

                                motor_left_state_data.phase_current = motor_data.phase_current_left;
                                motor_left_state_data.rpm = motor_data.speed_rpm_left;
                                motor_left_state_data.position_deg = motor_data.position_deg_left;

                                motor_right_state_data.phase_current = motor_data.phase_current_right;
                                motor_right_state_data.rpm = motor_data.speed_rpm_right;
                                motor_right_state_data.position_deg = motor_data.position_deg_right;

                                motor_left_state_data.over_temperature_fault = (motor_data.error_code_left & (1 << 4)) != 0;
                                motor_left_state_data.stall_fault = (motor_data.error_code_left & (1 << 3)) != 0;
                                motor_left_state_data.phase_overcurrent_fault = (motor_data.error_code_left & (1 << 2)) != 0;
                                motor_left_state_data.overcurrent_fault = (motor_data.error_code_left & (1 << 1)) != 0;
                                motor_left_state_data.sensor_fault = (motor_data.error_code_left & (1 << 0)) != 0;

                                motor_right_state_data.over_temperature_fault = (motor_data.error_code_right & (1 << 4)) != 0;
                                motor_right_state_data.stall_fault = (motor_data.error_code_right & (1 << 3)) != 0;
                                motor_right_state_data.phase_overcurrent_fault = (motor_data.error_code_right & (1 << 2)) != 0;
                                motor_right_state_data.overcurrent_fault = (motor_data.error_code_right & (1 << 1)) != 0;
                                motor_right_state_data.sensor_fault = (motor_data.error_code_right & (1 << 0)) != 0;

                                // 计算里程
                                double dl = -(motor_data.position_deg_left - last_motor_data.position_deg_left) * M_PI / 180.0 * wheel_radius;
                                double dr = -(motor_data.position_deg_right - last_motor_data.position_deg_right) * M_PI / 180.0 * wheel_radius;
                                dl *= odom_compensation_ratio;
                                dr *= odom_compensation_ratio;

                                // 角度跳变处理
                                int loop_dl = 0;
                                while (dl > M_PI * wheel_radius && loop_dl++ < 5)
                                    dl -= 2 * M_PI * wheel_radius;
                                loop_dl = 0;
                                while (dl < -M_PI * wheel_radius && loop_dl++ < 5)
                                    dl += 2 * M_PI * wheel_radius;
                                int loop_dr = 0;
                                while (dr > M_PI * wheel_radius && loop_dr++ < 5)
                                    dr -= 2 * M_PI * wheel_radius;
                                loop_dr = 0;
                                while (dr < -M_PI * wheel_radius && loop_dr++ < 5)
                                    dr += 2 * M_PI * wheel_radius;

                                double dc = (dl + dr) / 2.0;
                                double dyaw = (dr - dl) / (2.0 * chassis_radius);

                                float sin_yaw, cos_yaw;
                                sincosf(odom_data_raw.yaw + dyaw * 0.5f, &sin_yaw, &cos_yaw);
                                odom_data_raw.x += dc * cos_yaw;
                                odom_data_raw.y += dc * sin_yaw;
                                odom_data_raw.yaw = angles::normalize_angle(odom_data_raw.yaw + dyaw);

                                // 计算速度
                                double vl = (motor_data.speed_rpm_left / 60.0) * 2.0 * M_PI * wheel_radius;
                                double vr = (motor_data.speed_rpm_right / 60.0) * 2.0 * M_PI * wheel_radius;
                                vl *= odom_compensation_ratio;
                                vr *= odom_compensation_ratio;

                                odom_data_raw.vx = (vl + vr) / 2.0;
                                odom_data_raw.vyaw = (vr - vl) / (2.0 * chassis_radius);

                                // 更新里程计
                                odom_data.header.stamp = motor_data.header_stamp;

                                odom_data.pose.pose.position.x = odom_data_raw.x;
                                odom_data.pose.pose.position.y = odom_data_raw.y;
                                odom_data.pose.pose.orientation = tf::createQuaternionMsgFromYaw(odom_data_raw.yaw);
                                odom_data.twist.twist.linear.x = odom_data_raw.vx;
                                odom_data.twist.twist.angular.z = odom_data_raw.vyaw;

                                // 默认协方差
                                for (int i = 0; i < 36; i++)
                                {
                                    odom_data.pose.covariance[i] = 0.0;
                                }

                                odom_data.pose.covariance[0] = 0.01;  // x
                                odom_data.pose.covariance[7] = 0.01;  // y
                                odom_data.pose.covariance[35] = 0.05; // yaw
                                odom_data.pose.covariance[14] = 1e6;  // z
                                odom_data.pose.covariance[21] = 1e6;  // roll
                                odom_data.pose.covariance[28] = 1e6;  // pitch

                                for (int i = 0; i < 36; i++)
                                {
                                    odom_data.twist.covariance[i] = 0.0;
                                }

                                odom_data.twist.covariance[0] = 0.01;  // vx
                                odom_data.twist.covariance[35] = 0.05; // vyaw
                                odom_data.twist.covariance[7] = 1e6;   // vy (差速一般没有)
                                odom_data.twist.covariance[14] = 1e6;  // vz
                                odom_data.twist.covariance[21] = 1e6;  // vroll
                                odom_data.twist.covariance[28] = 1e6;  // vpitch

                                motor_left_state_pub.publish(motor_left_state_data);
                                motor_right_state_pub.publish(motor_right_state_data);

                                odom_pub.publish(odom_data);

                                // 发布里程计tf变换
                                if (publish_tf)
                                {
                                    if (odom_data.header.stamp != last_odom_tf_publish_time)
                                    {
                                        odom_trans.header = odom_data.header;
                                        odom_trans.child_frame_id = LOCALIZATION_BASE_LINK;

                                        // 静止时同样发布有效姿态，避免初始四元数全零。
                                        odom_trans.transform.translation.x = odom_data.pose.pose.position.x;
                                        odom_trans.transform.translation.y = odom_data.pose.pose.position.y;
                                        odom_trans.transform.rotation = odom_data.pose.pose.orientation;
                                    }

                                    try
                                    {
                                        tf_odom_to_base_footprint->sendTransform(odom_trans);
                                    }
                                    catch (...)
                                    {
                                        ROS_WARN("%s：无法发送变换。", TAG);
                                    }

                                    last_odom_tf_publish_time = odom_data.header.stamp;
                                }

                                last_motor_data = motor_data;
                            }

                        }
                        left_feedback_pending = false;
                    }
                }
            }

            // 无论成功、超时还是坏包，都必须轮到另一侧接收指令（含零速度）。
            comm_state = static_cast<uint8_t>(motor_safety::next_motor(comm_state));

            ROS_INFO_THROTTLE(5.0,
                "%s：UDP目标=%s:%d，最近提交发送的左/右协议RPM=%d/%d，左/右有效反馈间隔=%.3f/%.3fs，故障锁定=%s。",
                TAG, ip_address.c_str(), port, last_sent_left_rpm, last_sent_right_rpm,
                motor_guard.feedback_age(0, steady_seconds()), motor_guard.feedback_age(1, steady_seconds()),
                motor_guard.fault_latched() ? "是" : "否");

            // 循环频率控制
            rate.sleep();
        }

        // 速度归零
        packet_send_buffer[1] = 0x64;
        packet_send_buffer[2] = 0x00;
        packet_send_buffer[3] = 0x00;
        packet_send_buffer[4] = 0x00;
        packet_send_buffer[5] = 0x00;
        packet_send_buffer[6] = 0x00;
        packet_send_buffer[7] = 0x00;
        packet_send_buffer[8] = 0x00;

        packet_send_buffer[0] = MOTOR_LEFT_ID;
        packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));

        packet_send_buffer[0] = MOTOR_RIGHT_ID;
        packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        close(sock);
        sock = -1;
    }

    else
    {
        return 1;
    }

    if (tf_odom_to_base_footprint != NULL)
    {
        tf_odom_to_base_footprint.reset();
    }

    return 0;
}
