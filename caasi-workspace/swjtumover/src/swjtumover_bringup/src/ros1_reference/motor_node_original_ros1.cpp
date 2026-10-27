#include <ros/ros.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <chrono>
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

// 底盘参数
double chassis_radius = 0;
double wheel_radius = 0;
double odom_compensation_ratio = 1;

// 是否发布里程计tf参数
bool publish_tf;

// 定义UDP
int sock = 0;
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

    // 创建套接字
    if ((sock = socket(AF_INET, SOCK_DGRAM, 0)) < 0)
    {
        ROS_ERROR("%s：创建套接字失败。", TAG);

        return ret;
    }

    memset(&serv_addr, '0', sizeof(serv_addr));

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);

    // 将地址从文本转换为二进制
    if (inet_pton(AF_INET, ip_address.c_str(), &serv_addr.sin_addr) <= 0)
    {
        ROS_ERROR("%s：无效地址/地址不支持。", TAG);

        return ret;
    }

    timeval tv_recv{0, 5000};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv));
    timeval tv_send{0, 10000};
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send));

    ROS_INFO("%s：UDP连接成功。", TAG);

    ret = true;

    return ret;
}

// 回调函数
// 速度控制回调
void cmd_vel_callback(const geometry_msgs::Twist::ConstPtr &msg)
{
    // 计算由角速度产生的线速度
    double line_speed = msg->angular.z * chassis_radius;

    // 计算车轮速度
    double speed_left = msg->linear.x - line_speed;
    double speed_right = msg->linear.x + line_speed;

    // 解算为电机 RPM
    const float rpm_scale = 60.0f / (2.0f * M_PI * wheel_radius);
    motor_speed_cmd_data.speed_rpm_left = speed_left * rpm_scale;
    motor_speed_cmd_data.speed_rpm_right = speed_right * rpm_scale;

    // 防止电机速度溢出
    motor_speed_cmd_data.speed_rpm_left =
        abs(motor_speed_cmd_data.speed_rpm_left) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_left) : motor_speed_cmd_data.speed_rpm_left;
    motor_speed_cmd_data.speed_rpm_right =
        abs(motor_speed_cmd_data.speed_rpm_right) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_right) : motor_speed_cmd_data.speed_rpm_right;
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

    node_handle_param.param<double>("chassis_radius", chassis_radius, 0.103);
    node_handle_param.param<double>("wheel_radius", wheel_radius, 0.0535);
    node_handle_param.param<double>("odom_compensation_ratio", odom_compensation_ratio, 1.0);

    node_handle_param.param<bool>("publish_tf", publish_tf, true);

    // 初始化系统
    if (udp_init())
    {
        // 初始化订阅器
        cmd_vel_sub = node_handle.subscribe<geometry_msgs::Twist>("cmd_vel", 10, cmd_vel_callback);

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

        // 定义循环速度控制
        auto rate = ros::Rate(control_freq * 2);

        while (node_handle.ok())
        {
            // 处理回调函数
            ros::spinOnce();

            // 组装发送数据
            packet_send_buffer[0] = comm_state == STATE_CONTROL_LEFT_MOTOR ? MOTOR_LEFT_ID : MOTOR_RIGHT_ID;
            packet_send_buffer[1] = 0x64;

            int16_t speed_rpm = comm_state == STATE_CONTROL_LEFT_MOTOR ? motor_speed_cmd_data.speed_rpm_left : -motor_speed_cmd_data.speed_rpm_right;
            packet_send_buffer[2] = (uint8_t)(speed_rpm >> 8);
            packet_send_buffer[3] = (uint8_t)(speed_rpm & 0xff);

            packet_send_buffer[4] = 0x00;
            packet_send_buffer[5] = 0x00;

            float time_per_rpm = 1.0f / wheel_acc;
            uint8_t acc_param = min<uint8_t>(255, static_cast<uint8_t>(time_per_rpm * 10000.0f + 0.5f));
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
            udp_error |= (sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
                                 (struct sockaddr *)&serv_addr, sizeof(serv_addr)) == -1);

            // 等待回收数据
            ssize_t total_recv_len = 0;

            if (!udp_error)
            {
                double start_time = ros::Time::now().toSec();

                do
                {
                    socklen_t addr_len = sizeof(serv_addr);
                    ssize_t recv_len = recvfrom(sock, packet_receive_buffer + total_recv_len, MOTOR_RECV_BUFFER_SIZE - total_recv_len, 0,
                                                (struct sockaddr *)&serv_addr, &addr_len);

                    if (recv_len > 0)
                    {
                        total_recv_len += recv_len;
                    }
                } while (total_recv_len < MOTOR_RECV_BUFFER_SIZE && abs(ros::Time::now().toSec() - start_time) < 0.01);
            }

            if (udp_error)
            {
                ROS_ERROR("%s：UDP连接失败，准备重新连接。", TAG);

                // 尝试重连
                udp_init();
            }
            else if (total_recv_len == MOTOR_RECV_BUFFER_SIZE)
            {
                motor_data.header_stamp = ros::Time::now();

                if (crc8_maxim(packet_receive_buffer, MOTOR_RECV_BUFFER_SIZE - 1) == packet_receive_buffer[MOTOR_RECV_BUFFER_SIZE - 1])
                {
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

                        // 更新控制状态
                        comm_state =
                            (comm_state == STATE_CONTROL_LEFT_MOTOR) ? STATE_CONTROL_RIGHT_MOTOR : STATE_CONTROL_LEFT_MOTOR;
                    }
                    else if (comm_state == STATE_CONTROL_RIGHT_MOTOR && packet_receive_buffer[0] == MOTOR_RIGHT_ID)
                    {
                        motor_data.phase_current_right = abs(((float)phase_current_recv / 32767.0f) * 8.0f);
                        motor_data.speed_rpm_right = -speed_rpm_recv;
                        motor_data.position_deg_right = 360.0f - ((float)position_deg_recv * 360.0f / 32767.0f);
                        motor_data.error_code_right = error_code_recv;

                        // 右电机已获取，则说明可以更新发布数据
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

                                    if (abs(odom_data.twist.twist.linear.x) > 1e-4 ||
                                        abs(odom_data.twist.twist.angular.z) > 1e-4)
                                    {
                                        odom_trans.transform.translation.x = odom_data.pose.pose.position.x;
                                        odom_trans.transform.translation.y = odom_data.pose.pose.position.y;
                                        odom_trans.transform.rotation = odom_data.pose.pose.orientation;
                                    }
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

                        // 更新控制状态
                        comm_state =
                            (comm_state == STATE_CONTROL_LEFT_MOTOR) ? STATE_CONTROL_RIGHT_MOTOR : STATE_CONTROL_LEFT_MOTOR;
                    }
                }
            }

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
    }

    if (tf_odom_to_base_footprint != NULL)
    {
        tf_odom_to_base_footprint.reset();
    }

    return 0;
}