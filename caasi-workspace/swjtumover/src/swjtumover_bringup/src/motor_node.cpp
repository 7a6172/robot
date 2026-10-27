// ROS 2 port of swjtumover_bringup/motor_node (the hardened variant from swjtumover01).
//
// Fidelity notes, because this is a migration and not a rewrite:
//   * the UDP protocol, packet layout, CRC, odometry maths, covariance values and the
//     left/right alternation are unchanged from ROS 1;
//   * topic names are unchanged on purpose (/cmd_vel, /odom, /motor_state/left,
//     /motor_state/right) so the ROS 1 and ROS 2 systems can be compared directly;
//   * motor_safety.h (command watchdog, feedback timeout, fault latch) is carried over
//     verbatim: it is plain C++ and it is the part that makes the ROS 1 incident
//     (a command latched after the process died) unrepeatable;
//   * the ROS 1 node created a tf2_ros::TransformListener it never used; it is not ported.
//
// ROS 1 -> ROS 2 mapping: NodeHandle -> rclcpp::Node, private "~/motor" params -> "motor.*",
// ros::WallRate -> rclcpp::WallRate, spinOnce -> spin_some,
// tf::createQuaternionMsgFromYaw -> tf2 quaternion maths, ROS_*_THROTTLE -> RCLCPP_*_THROTTLE.

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <swjtumover_msgs/msg/motor_state.hpp>

#include <robot_frames.h>
#include <utils/crc8_maxim.h>
#include <utils/motor_safety.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <clocale>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#define NODE_NAME "motor_node"
#define TAG "机器人电机驱动"

namespace
{

constexpr int STATE_CONTROL_LEFT_MOTOR = 0;
constexpr int STATE_CONTROL_RIGHT_MOTOR = 1;
constexpr int MOTOR_LEFT_ID = 1;
constexpr int MOTOR_RIGHT_ID = 2;
constexpr int MOTOR_CMD_BUFFER_SIZE = 10;
constexpr int MOTOR_RECV_BUFFER_SIZE = 10;

double steady_seconds()
{
  return std::chrono::duration<double>(
           std::chrono::steady_clock::now().time_since_epoch()).count();
}

struct MotorSpeedCmd
{
  int16_t speed_rpm_left = 0;
  int16_t speed_rpm_right = 0;
};

struct MotorData
{
  rclcpp::Time header_stamp{0, 0, RCL_ROS_TIME};
  float phase_current_left = 0.0f;
  float phase_current_right = 0.0f;
  int16_t speed_rpm_left = 0;
  int16_t speed_rpm_right = 0;
  float position_deg_left = 0.0f;
  float position_deg_right = 0.0f;
  uint8_t error_code_left = 0;
  uint8_t error_code_right = 0;
};

struct OdomData
{
  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
  double vx = 0.0;
  double vyaw = 0.0;
};

//! Normalise to (-pi, pi], as angles::normalize_angle did in ROS 1.
double normalize_angle(double angle)
{
  return std::remainder(angle, 2.0 * M_PI);
}

}  // namespace

class MotorNode : public rclcpp::Node
{
public:
  MotorNode() : rclcpp::Node(NODE_NAME)
  {
    setlocale(LC_CTYPE, "zh_CN.utf8");
    RCLCPP_INFO(get_logger(), "%s：节点已启动。", TAG);

    declare_parameters();
    if (!parameters_valid()) {
      RCLCPP_FATAL(get_logger(), "%s：电机参数无效，拒绝启动。", TAG);
      throw std::runtime_error("invalid motor parameters");
    }
    guard_ = motor_safety::Guard(cmd_vel_timeout_, motor_feedback_timeout_, steady_seconds());

    if (!udp_init()) {
      throw std::runtime_error("motor UDP initialisation failed");
    }

    cmd_vel_sub_ = create_subscription<geometry_msgs::msg::Twist>(
      "cmd_vel", 1,
      [this](const geometry_msgs::msg::Twist::SharedPtr msg) { on_cmd_vel(msg); });
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 1);
    motor_left_state_pub_ =
      create_publisher<swjtumover_msgs::msg::MotorState>("motor_state/left", 1);
    motor_right_state_pub_ =
      create_publisher<swjtumover_msgs::msg::MotorState>("motor_state/right", 1);
    tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

    odom_data_.header.frame_id = LOCALIZATION_ODOM;
    odom_data_.child_frame_id = LOCALIZATION_BASE_LINK;
    tf2::Quaternion zero;
    zero.setRPY(0.0, 0.0, 0.0);
    odom_data_.pose.pose.orientation = tf2::toMsg(zero);
  }

  double control_freq() const { return control_freq_; }

  //! One control iteration: exchange one packet with the board.
  void step()
  {
    rclcpp::spin_some(shared_from_this());
    const double wall_now = steady_seconds();

    const bool was_faulted = guard_.fault_latched();
    guard_.check_feedback(wall_now);
    if (guard_.fault_latched()) {
      if (!was_faulted) {
        motor_ready_ = false;
        left_feedback_pending_ = false;
      }
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000,
        "%s：电机反馈超时，已锁定零速度；左反馈间隔 %.3fs，右反馈间隔 %.3fs。修复通信后需重启节点。",
        TAG, guard_.feedback_age(0, wall_now), guard_.feedback_age(1, wall_now));
    } else if (!guard_.command_fresh(wall_now) &&
               (cmd_.speed_rpm_left != 0 || cmd_.speed_rpm_right != 0)) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000,
        "%s：cmd_vel 超时，输出零速度。", TAG);
    }

    const bool left_turn = comm_state_ == STATE_CONTROL_LEFT_MOTOR;
    packet_send_buffer_[0] = left_turn ? MOTOR_LEFT_ID : MOTOR_RIGHT_ID;
    packet_send_buffer_[1] = 0x64;

    int16_t speed_rpm = left_turn ? cmd_.speed_rpm_left : -cmd_.speed_rpm_right;
    if (!guard_.allow_motion(wall_now)) {
      speed_rpm = 0;
    }
    packet_send_buffer_[2] = static_cast<uint8_t>(speed_rpm >> 8);
    packet_send_buffer_[3] = static_cast<uint8_t>(speed_rpm & 0xff);
    packet_send_buffer_[4] = 0x00;
    packet_send_buffer_[5] = 0x00;

    const float time_per_rpm = 1.0f / static_cast<float>(wheel_acc_);
    packet_send_buffer_[6] =
      static_cast<uint8_t>(std::min(255.0f, time_per_rpm * 10000.0f + 0.5f));
    packet_send_buffer_[7] = 0x00;
    packet_send_buffer_[8] = 0x00;
    packet_send_buffer_[MOTOR_CMD_BUFFER_SIZE - 1] =
      crc8_maxim(packet_send_buffer_, MOTOR_CMD_BUFFER_SIZE - 1);

    const bool udp_error =
      sendto(sock_, packet_send_buffer_, MOTOR_CMD_BUFFER_SIZE, 0,
             reinterpret_cast<struct sockaddr *>(&serv_addr_), sizeof(serv_addr_)) !=
      MOTOR_CMD_BUFFER_SIZE;
    if (!udp_error) {
      if (left_turn) {
        last_sent_left_rpm_ = speed_rpm;
      } else {
        last_sent_right_rpm_ = speed_rpm;
      }
    }

    ssize_t total_recv_len = 0;
    if (!udp_error) {
      const double deadline = steady_seconds() + 0.01;
      do {
        // 接收地址独立保存，绝不能让回包改写发送目标 serv_addr。
        sockaddr_in reply_addr{};
        socklen_t addr_len = sizeof(reply_addr);
        uint8_t datagram[MOTOR_RECV_BUFFER_SIZE + 1] = {};
        const ssize_t recv_len = recvfrom(sock_, datagram, sizeof(datagram), 0,
                                          reinterpret_cast<struct sockaddr *>(&reply_addr),
                                          &addr_len);
        if (recv_len < 0) {
          if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
            continue;
          }
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000,
            "%s：接收电机反馈失败: %s", TAG, strerror(errno));
          break;
        }
        if (recv_len != MOTOR_RECV_BUFFER_SIZE ||
            reply_addr.sin_family != AF_INET ||
            reply_addr.sin_addr.s_addr != serv_addr_.sin_addr.s_addr ||
            datagram[0] != packet_send_buffer_[0] ||
            crc8_maxim(datagram, MOTOR_RECV_BUFFER_SIZE - 1) !=
              datagram[MOTOR_RECV_BUFFER_SIZE - 1]) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000,
            "%s：忽略无效电机反馈，长度=%ld，ID=%u，当前请求ID=%u；检查回包来源、长度和CRC。",
            TAG, static_cast<long>(recv_len), static_cast<unsigned>(datagram[0]),
            static_cast<unsigned>(packet_send_buffer_[0]));
          continue;
        }
        std::copy(datagram, datagram + MOTOR_RECV_BUFFER_SIZE, packet_receive_buffer_);
        total_recv_len = MOTOR_RECV_BUFFER_SIZE;
        break;
      } while (rclcpp::ok() && steady_seconds() < deadline);
    }

    if (udp_error) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 1000,
        "%s：UDP发送失败，已锁定零速度，准备重新创建套接字。", TAG);
      guard_.latch_fault();
      motor_ready_ = false;
      left_feedback_pending_ = false;
      udp_init();
    } else if (total_recv_len == MOTOR_RECV_BUFFER_SIZE &&
               crc8_maxim(packet_receive_buffer_, MOTOR_RECV_BUFFER_SIZE - 1) ==
                 packet_receive_buffer_[MOTOR_RECV_BUFFER_SIZE - 1]) {
      handle_feedback(left_turn);
    }

    // 无论成功、超时还是坏包，都必须轮到另一侧接收指令（含零速度）。
    comm_state_ = static_cast<uint8_t>(motor_safety::next_motor(comm_state_));

    RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 5000,
      "%s：UDP目标=%s:%d，最近提交发送的左/右协议RPM=%d/%d，左/右有效反馈间隔=%.3f/%.3fs，故障锁定=%s。",
      TAG, ip_address_.c_str(), port_, last_sent_left_rpm_, last_sent_right_rpm_,
      guard_.feedback_age(0, steady_seconds()), guard_.feedback_age(1, steady_seconds()),
      guard_.fault_latched() ? "是" : "否");
  }

  //! Final zero-velocity flush, then close the socket. Called once on shutdown.
  void shutdown_motors()
  {
    if (sock_ < 0) {
      return;
    }
    packet_send_buffer_[1] = 0x64;
    for (int i = 2; i <= 8; ++i) {
      packet_send_buffer_[i] = 0x00;
    }
    for (const int id : {MOTOR_LEFT_ID, MOTOR_RIGHT_ID}) {
      packet_send_buffer_[0] = static_cast<uint8_t>(id);
      packet_send_buffer_[MOTOR_CMD_BUFFER_SIZE - 1] =
        crc8_maxim(packet_send_buffer_, MOTOR_CMD_BUFFER_SIZE - 1);
      for (int repeat = 0; repeat < 2; ++repeat) {
        sendto(sock_, packet_send_buffer_, MOTOR_CMD_BUFFER_SIZE, 0,
               reinterpret_cast<struct sockaddr *>(&serv_addr_), sizeof(serv_addr_));
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
      }
    }
    close(sock_);
    sock_ = -1;
  }

private:
  //! Declare a numeric parameter from the ROS 1 style configuration, accepting int or double.
  /*!
   * ROS 1's `NodeHandle::param<float>` converted an integer YAML value for us, so
   * `control_freq: 50` was fine. ROS 2 rejects an integer override for a double parameter
   * ("parameter is of type double, setting it to integer is not allowed"), which would make
   * every ROS 1 configuration file fail to load after the migration. The override's own type
   * therefore decides how the parameter is declared.
   */
  double declare_numeric(const std::string & name, double fallback)
  {
    const auto overrides = get_node_parameters_interface()->get_parameter_overrides();
    auto it = overrides.find(name);
    if (it != overrides.end()) {
      const auto type = it->second.get_type();
      if (type == rclcpp::ParameterType::PARAMETER_INTEGER) {
        return static_cast<double>(
          declare_parameter<int64_t>(name, static_cast<int64_t>(std::llround(fallback))));
      }
      if (type == rclcpp::ParameterType::PARAMETER_DOUBLE) {
        return declare_parameter<double>(name, fallback);
      }
      throw std::runtime_error(name + ": expected an integer or a double");
    }
    return declare_parameter<double>(name, fallback);
  }

  //! Same idea for parameters that are integers in the ROS 1 files.
  int64_t declare_integer(const std::string & name, int64_t fallback)
  {
    const auto overrides = get_node_parameters_interface()->get_parameter_overrides();
    auto it = overrides.find(name);
    if (it != overrides.end()) {
      const auto type = it->second.get_type();
      if (type == rclcpp::ParameterType::PARAMETER_DOUBLE) {
        return static_cast<int64_t>(std::llround(declare_parameter<double>(
          name, static_cast<double>(fallback))));
      }
      if (type == rclcpp::ParameterType::PARAMETER_INTEGER) {
        return declare_parameter<int64_t>(name, fallback);
      }
      throw std::runtime_error(name + ": expected an integer or a double");
    }
    return declare_parameter<int64_t>(name, fallback);
  }

  void declare_parameters()
  {
    control_freq_ = declare_numeric("motor.control_freq", 50.0);
    ip_address_ = declare_parameter<std::string>("motor.ip_address", "192.168.100.100");
    port_ = static_cast<int>(declare_integer("motor.port", 23));
    wheel_max_speed_rpm_ = static_cast<int>(
      declare_integer("motor.wheel_max_speed_rpm", 300));
    wheel_acc_ = static_cast<int>(declare_integer("motor.wheel_acc", 10000));
    cmd_vel_timeout_ = declare_numeric("motor.cmd_vel_timeout", 0.5);
    motor_feedback_timeout_ = declare_numeric("motor.motor_feedback_timeout", 0.5);
    chassis_radius_ = declare_numeric("motor.chassis_radius", 0.103);
    wheel_radius_ = declare_numeric("motor.wheel_radius", 0.0535);
    odom_compensation_ratio_ = declare_numeric("motor.odom_compensation_ratio", 1.0);
    publish_tf_ = declare_parameter<bool>("motor.publish_tf", true);
  }

  bool parameters_valid() const
  {
    return std::isfinite(control_freq_) && control_freq_ > 0 &&
           std::isfinite(cmd_vel_timeout_) && cmd_vel_timeout_ > 0 &&
           std::isfinite(motor_feedback_timeout_) && motor_feedback_timeout_ > 0 &&
           std::isfinite(chassis_radius_) && chassis_radius_ > 0 &&
           std::isfinite(wheel_radius_) && wheel_radius_ > 0 &&
           std::isfinite(odom_compensation_ratio_) && odom_compensation_ratio_ > 0 &&
           wheel_acc_ > 0 && wheel_max_speed_rpm_ > 0 &&
           wheel_max_speed_rpm_ <= std::numeric_limits<int16_t>::max() &&
           port_ > 0 && port_ <= 65535;
  }

  bool udp_init()
  {
    if (sock_ >= 0) {
      close(sock_);
      sock_ = -1;
    }
    if ((sock_ = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
      RCLCPP_ERROR(get_logger(), "%s：创建套接字失败。", TAG);
      return false;
    }
    memset(&serv_addr_, 0, sizeof(serv_addr_));
    serv_addr_.sin_family = AF_INET;
    serv_addr_.sin_port = htons(static_cast<uint16_t>(port_));
    if (inet_pton(AF_INET, ip_address_.c_str(), &serv_addr_.sin_addr) <= 0) {
      RCLCPP_ERROR(get_logger(), "%s：无效地址/地址不支持。", TAG);
      close(sock_);
      sock_ = -1;
      return false;
    }
    timeval tv_recv{0, 5000};
    timeval tv_send{0, 10000};
    if (setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv)) != 0 ||
        setsockopt(sock_, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send)) != 0) {
      RCLCPP_ERROR(get_logger(), "%s：无法设置 UDP 超时: %s", TAG, strerror(errno));
      close(sock_);
      sock_ = -1;
      return false;
    }
    RCLCPP_INFO(get_logger(), "%s：UDP套接字已创建，等待电机有效反馈。", TAG);
    return true;
  }

  void on_cmd_vel(const geometry_msgs::msg::Twist::SharedPtr msg)
  {
    if (!std::isfinite(msg->linear.x) || !std::isfinite(msg->angular.z)) {
      cmd_.speed_rpm_left = 0;
      cmd_.speed_rpm_right = 0;
      guard_.invalidate_command();
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 1000,
        "%s：速度含无效数值，输出零速度。", TAG);
      return;
    }
    const double line_speed = msg->angular.z * chassis_radius_;
    const double speed_left = msg->linear.x - line_speed;
    const double speed_right = msg->linear.x + line_speed;

    const double rpm_scale = 60.0 / (2.0 * M_PI * wheel_radius_);
    const double left_rpm = speed_left * rpm_scale;
    const double right_rpm = speed_right * rpm_scale;
    if (!std::isfinite(left_rpm) || !std::isfinite(right_rpm)) {
      cmd_.speed_rpm_left = 0;
      cmd_.speed_rpm_right = 0;
      guard_.invalidate_command();
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 1000,
        "%s：转速计算溢出，输出零速度。", TAG);
      return;
    }
    const double limit = static_cast<double>(wheel_max_speed_rpm_);
    cmd_.speed_rpm_left = static_cast<int16_t>(std::clamp(left_rpm, -limit, limit));
    cmd_.speed_rpm_right = static_cast<int16_t>(std::clamp(right_rpm, -limit, limit));
    guard_.command_received(steady_seconds());
  }

  void handle_feedback(bool left_turn)
  {
    motor_data_.header_stamp = now();
    guard_.feedback_received(comm_state_, steady_seconds());

    const auto phase_current_recv = static_cast<int16_t>(
      (packet_receive_buffer_[2] << 8) | packet_receive_buffer_[3]);
    const auto speed_rpm_recv = static_cast<int16_t>(
      (packet_receive_buffer_[4] << 8) | packet_receive_buffer_[5]);
    const auto position_deg_recv = static_cast<uint16_t>(
      (packet_receive_buffer_[6] << 8) | packet_receive_buffer_[7]);
    const uint8_t error_code_recv = packet_receive_buffer_[8];

    if (left_turn && packet_receive_buffer_[0] == MOTOR_LEFT_ID) {
      motor_data_.phase_current_left =
        std::abs((static_cast<float>(phase_current_recv) / 32767.0f) * 8.0f);
      motor_data_.speed_rpm_left = speed_rpm_recv;
      motor_data_.position_deg_left =
        static_cast<float>(position_deg_recv) * 360.0f / 32767.0f;
      motor_data_.error_code_left = error_code_recv;
      left_feedback_pending_ = true;
    } else if (!left_turn && packet_receive_buffer_[0] == MOTOR_RIGHT_ID) {
      motor_data_.phase_current_right =
        std::abs((static_cast<float>(phase_current_recv) / 32767.0f) * 8.0f);
      motor_data_.speed_rpm_right = static_cast<int16_t>(-speed_rpm_recv);
      motor_data_.position_deg_right =
        360.0f - (static_cast<float>(position_deg_recv) * 360.0f / 32767.0f);
      motor_data_.error_code_right = error_code_recv;

      // 只有本轮左、右有效反馈齐全时才更新里程计。
      // 不能在一侧掉线后用旧位置伪造新的 odom/TF。
      if (left_feedback_pending_ && guard_.feedback_fresh(steady_seconds())) {
        if (!motor_ready_) {
          last_motor_data_ = motor_data_;
          motor_ready_ = true;
        } else {
          publish_state_and_odom();
          last_motor_data_ = motor_data_;
        }
      }
      left_feedback_pending_ = false;
    }
  }

  void publish_state_and_odom()
  {
    motor_left_state_data_.header.stamp = motor_data_.header_stamp;
    motor_right_state_data_.header = motor_left_state_data_.header;

    motor_left_state_data_.phase_current = motor_data_.phase_current_left;
    motor_left_state_data_.rpm = motor_data_.speed_rpm_left;
    motor_left_state_data_.position_deg = motor_data_.position_deg_left;

    motor_right_state_data_.phase_current = motor_data_.phase_current_right;
    motor_right_state_data_.rpm = motor_data_.speed_rpm_right;
    motor_right_state_data_.position_deg = motor_data_.position_deg_right;

    motor_left_state_data_.over_temperature_fault = (motor_data_.error_code_left & (1 << 4)) != 0;
    motor_left_state_data_.stall_fault = (motor_data_.error_code_left & (1 << 3)) != 0;
    motor_left_state_data_.phase_overcurrent_fault = (motor_data_.error_code_left & (1 << 2)) != 0;
    motor_left_state_data_.overcurrent_fault = (motor_data_.error_code_left & (1 << 1)) != 0;
    motor_left_state_data_.sensor_fault = (motor_data_.error_code_left & (1 << 0)) != 0;

    motor_right_state_data_.over_temperature_fault = (motor_data_.error_code_right & (1 << 4)) != 0;
    motor_right_state_data_.stall_fault = (motor_data_.error_code_right & (1 << 3)) != 0;
    motor_right_state_data_.phase_overcurrent_fault = (motor_data_.error_code_right & (1 << 2)) != 0;
    motor_right_state_data_.overcurrent_fault = (motor_data_.error_code_right & (1 << 1)) != 0;
    motor_right_state_data_.sensor_fault = (motor_data_.error_code_right & (1 << 0)) != 0;

    // 计算里程
    double dl = -(motor_data_.position_deg_left - last_motor_data_.position_deg_left) *
                M_PI / 180.0 * wheel_radius_;
    double dr = -(motor_data_.position_deg_right - last_motor_data_.position_deg_right) *
                M_PI / 180.0 * wheel_radius_;
    dl *= odom_compensation_ratio_;
    dr *= odom_compensation_ratio_;

    // 角度跳变处理
    int loop = 0;
    while (dl > M_PI * wheel_radius_ && loop++ < 5) {
      dl -= 2 * M_PI * wheel_radius_;
    }
    loop = 0;
    while (dl < -M_PI * wheel_radius_ && loop++ < 5) {
      dl += 2 * M_PI * wheel_radius_;
    }
    loop = 0;
    while (dr > M_PI * wheel_radius_ && loop++ < 5) {
      dr -= 2 * M_PI * wheel_radius_;
    }
    loop = 0;
    while (dr < -M_PI * wheel_radius_ && loop++ < 5) {
      dr += 2 * M_PI * wheel_radius_;
    }

    const double dc = (dl + dr) / 2.0;
    const double dyaw = (dr - dl) / (2.0 * chassis_radius_);

    float sin_yaw = 0.0f;
    float cos_yaw = 0.0f;
    sincosf(static_cast<float>(odom_raw_.yaw + dyaw * 0.5), &sin_yaw, &cos_yaw);
    odom_raw_.x += dc * cos_yaw;
    odom_raw_.y += dc * sin_yaw;
    odom_raw_.yaw = normalize_angle(odom_raw_.yaw + dyaw);

    double vl = (motor_data_.speed_rpm_left / 60.0) * 2.0 * M_PI * wheel_radius_;
    double vr = (motor_data_.speed_rpm_right / 60.0) * 2.0 * M_PI * wheel_radius_;
    vl *= odom_compensation_ratio_;
    vr *= odom_compensation_ratio_;
    odom_raw_.vx = (vl + vr) / 2.0;
    odom_raw_.vyaw = (vr - vl) / (2.0 * chassis_radius_);

    odom_data_.header.stamp = motor_data_.header_stamp;
    odom_data_.pose.pose.position.x = odom_raw_.x;
    odom_data_.pose.pose.position.y = odom_raw_.y;
    tf2::Quaternion q;
    q.setRPY(0.0, 0.0, odom_raw_.yaw);
    odom_data_.pose.pose.orientation = tf2::toMsg(q);
    odom_data_.twist.twist.linear.x = odom_raw_.vx;
    odom_data_.twist.twist.angular.z = odom_raw_.vyaw;

    for (int i = 0; i < 36; ++i) {
      odom_data_.pose.covariance[i] = 0.0;
      odom_data_.twist.covariance[i] = 0.0;
    }
    odom_data_.pose.covariance[0] = 0.01;    // x
    odom_data_.pose.covariance[7] = 0.01;    // y
    odom_data_.pose.covariance[35] = 0.05;   // yaw
    odom_data_.pose.covariance[14] = 1e6;    // z
    odom_data_.pose.covariance[21] = 1e6;    // roll
    odom_data_.pose.covariance[28] = 1e6;    // pitch
    odom_data_.twist.covariance[0] = 0.01;   // vx
    odom_data_.twist.covariance[35] = 0.05;  // vyaw
    odom_data_.twist.covariance[7] = 1e6;    // vy
    odom_data_.twist.covariance[14] = 1e6;   // vz
    odom_data_.twist.covariance[21] = 1e6;   // vroll
    odom_data_.twist.covariance[28] = 1e6;   // vpitch

    motor_left_state_pub_->publish(motor_left_state_data_);
    motor_right_state_pub_->publish(motor_right_state_data_);
    odom_pub_->publish(odom_data_);

    if (publish_tf_ &&
        rclcpp::Time(odom_data_.header.stamp) != last_odom_tf_publish_time_) {
      geometry_msgs::msg::TransformStamped transform;
      transform.header = odom_data_.header;
      transform.child_frame_id = LOCALIZATION_BASE_LINK;
      // 静止时同样发布有效姿态，避免初始四元数全零。
      transform.transform.translation.x = odom_data_.pose.pose.position.x;
      transform.transform.translation.y = odom_data_.pose.pose.position.y;
      transform.transform.rotation = odom_data_.pose.pose.orientation;
      tf_broadcaster_->sendTransform(transform);
      last_odom_tf_publish_time_ = rclcpp::Time(odom_data_.header.stamp);
    }
  }

  // parameters
  double control_freq_ = 50.0;
  std::string ip_address_;
  int port_ = 23;
  int wheel_max_speed_rpm_ = 300;
  int wheel_acc_ = 1000;
  double cmd_vel_timeout_ = 0.5;
  double motor_feedback_timeout_ = 0.5;
  double chassis_radius_ = 0.0;
  double wheel_radius_ = 0.0;
  double odom_compensation_ratio_ = 1.0;
  bool publish_tf_ = true;

  motor_safety::Guard guard_;
  int16_t last_sent_left_rpm_ = 0;
  int16_t last_sent_right_rpm_ = 0;

  int sock_ = -1;
  struct sockaddr_in serv_addr_ {};
  uint8_t comm_state_ = STATE_CONTROL_LEFT_MOTOR;
  uint8_t packet_receive_buffer_[MOTOR_RECV_BUFFER_SIZE] = {0x00};
  uint8_t packet_send_buffer_[MOTOR_CMD_BUFFER_SIZE] = {0x00};

  MotorSpeedCmd cmd_;
  MotorData motor_data_;
  MotorData last_motor_data_;
  OdomData odom_raw_;
  nav_msgs::msg::Odometry odom_data_;
  swjtumover_msgs::msg::MotorState motor_left_state_data_;
  swjtumover_msgs::msg::MotorState motor_right_state_data_;
  bool motor_ready_ = false;
  bool left_feedback_pending_ = false;

  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  rclcpp::Publisher<swjtumover_msgs::msg::MotorState>::SharedPtr motor_left_state_pub_;
  rclcpp::Publisher<swjtumover_msgs::msg::MotorState>::SharedPtr motor_right_state_pub_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::Time last_odom_tf_publish_time_{0, 0, RCL_ROS_TIME};
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  std::shared_ptr<MotorNode> node;
  try {
    node = std::make_shared<MotorNode>();
  } catch (const std::exception & err) {
    RCLCPP_FATAL(rclcpp::get_logger(NODE_NAME), "启动失败: %s", err.what());
    rclcpp::shutdown();
    return 1;
  }

  // The ROS 1 loop ran at 2x control_freq because it alternates left/right packets.
  rclcpp::WallRate rate(node->control_freq() * 2.0);
  while (rclcpp::ok()) {
    node->step();
    rate.sleep();
  }

  node->shutdown_motors();
  rclcpp::shutdown();
  return 0;
}
