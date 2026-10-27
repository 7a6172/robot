#include <ros/ros.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <linux/input.h>
#include <serial/serial.h>
#include <tf/tf.h>
#include <boost/thread.hpp>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include <std_msgs/Int8.h>
#include <tf/transform_datatypes.h>
#include <sstream>
#include <iomanip>
#include <std_msgs/String.h>

#define NODE_NAME "screen_handler"
#define TAG "屏幕驱动"

using namespace std;

// 定义参数
// 控制频率
float control_freq = 5;

// 连接参数
string ip_address;
int port;

// 包尾
uint8_t comm_tail = 0xff;

// 定义TCP
int sock = 0;
struct sockaddr_in serv_addr;

// 定义通讯参数
string packet_send_buffer;

// 定义二维码数据
string qrcode_text;
string last_qrcode_text;

// 定义接收器
ros::Subscriber qrcode_text_sub;

// 功能函数
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

// 发送数据
void send_data(string content)
{
    try
    {
        sendto(sock, content.c_str(), content.length(), 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        sendto(sock, (const uint8_t *)(&comm_tail), 1, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        sendto(sock, (const uint8_t *)(&comm_tail), 1, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        sendto(sock, (const uint8_t *)(&comm_tail), 1, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
    }
    catch (...)
    {
        ROS_ERROR("%s：UDP连接失败。", TAG);

        // 尝试重连
        udp_init();
    }
}

// 回调函数
// 二维码数据回调
void qrcode_text_callback(const std_msgs::String::ConstPtr &msg)
{
    if (msg->data != last_qrcode_text)
    {
        qrcode_text = msg->data;
        last_qrcode_text = qrcode_text;

        send_data("qrcode.txt=\"" + qrcode_text + "\"");
    }
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    ros::init(argc, argv, NODE_NAME);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 打印调试信息
    ROS_INFO("%s:节点已启动。", TAG);

    // 定义ROS节点处理程序
    ros::NodeHandle node_handle;

    // 定义ROS参数获取程序
    ros::NodeHandle node_handle_param("~/screen");

    // 获取参数
    node_handle_param.param<float>("control_freq", control_freq, 5);

    node_handle_param.param<string>("ip_address", ip_address, "192.168.100.100");
    node_handle_param.param<int>("port", port, 26);

    // 初始化系统
    if (udp_init())
    {
        // 初始化订阅器
        qrcode_text_sub = node_handle.subscribe<std_msgs::String>("qrcode_text", 1, qrcode_text_callback);

        // 定义循环速度控制
        auto rate = ros::Rate(control_freq);

        while (node_handle.ok())
        {
            // 处理回调函数
            ros::spinOnce();

            // 循环频率控制
            rate.sleep();
        }
    }

    return 0;
}
