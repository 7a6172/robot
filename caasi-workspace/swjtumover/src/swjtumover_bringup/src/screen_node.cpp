// ROS 2 port of swjtumover_bringup/screen_node.
//
// Fidelity notes:
//   * the wire format is unchanged: `qrcode.txt="<text>"` followed by three 0xff tail bytes,
//     sent to the screen board over UDP (default 192.168.100.100:26). Note the tail byte is
//     0xff here, not 0x00, so it must not be "unified" with any other project's framing;
//   * duplicate text is suppressed, exactly as in ROS 1;
//   * the topic name is unchanged: /qrcode_text (std_msgs/String).
//
// The only behaviour change is deliberate and small: a send failure is now reported and the
// socket is recreated on the next message, instead of being swallowed by a try/catch that
// sendto() can never throw into.

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>

#include <cerrno>
#include <clocale>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#define NODE_NAME "screen_handler"
#define TAG "screen driver"

namespace
{

//! The tail byte the board expects after the text frame. ROS 1 used 0xff.
constexpr uint8_t COMM_TAIL = 0xff;

//! One screen update as the datagrams it is sent as. Pure, so it can be tested.
std::vector<std::string> framed_datagrams(const std::string & text)
{
  std::vector<std::string> frames;
  frames.emplace_back("qrcode.txt=\"" + text + "\"");
  frames.emplace_back(1, static_cast<char>(COMM_TAIL));
  frames.emplace_back(1, static_cast<char>(COMM_TAIL));
  frames.emplace_back(1, static_cast<char>(COMM_TAIL));
  return frames;
}

}  // namespace

class ScreenNode : public rclcpp::Node
{
public:
  ScreenNode() : rclcpp::Node(NODE_NAME)
  {
    setlocale(LC_CTYPE, "zh_CN.utf8");
    RCLCPP_INFO(get_logger(), "%s: node started.", TAG);

    control_freq_ = declare_parameter<double>("screen.control_freq", 5.0);
    ip_address_ = declare_parameter<std::string>("screen.ip_address", "192.168.100.100");
    port_ = declare_parameter<int>("screen.port", 26);

    if (!udp_init()) {
      throw std::runtime_error("screen UDP initialisation failed");
    }

    qrcode_text_sub_ = create_subscription<std_msgs::msg::String>(
      "qrcode_text", 1,
      [this](const std_msgs::msg::String::SharedPtr msg) { on_qrcode_text(msg); });

    // The ROS 1 node slept at control_freq without sending anything periodically; the timer
    // keeps that liveness behaviour without inventing traffic.
    if (control_freq_ > 0.0) {
      timer_ = create_wall_timer(
        std::chrono::duration<double>(1.0 / control_freq_), []() {});
    }
  }

  ~ScreenNode() override
  {
    if (sock_ >= 0) {
      close(sock_);
      sock_ = -1;
    }
  }

private:
  bool udp_init()
  {
    if (sock_ >= 0) {
      close(sock_);
      sock_ = -1;
    }
    if ((sock_ = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
      RCLCPP_ERROR(get_logger(), "%s: failed to create the socket.", TAG);
      return false;
    }
    memset(&serv_addr_, 0, sizeof(serv_addr_));
    serv_addr_.sin_family = AF_INET;
    serv_addr_.sin_port = htons(static_cast<uint16_t>(port_));
    if (inet_pton(AF_INET, ip_address_.c_str(), &serv_addr_.sin_addr) <= 0) {
      RCLCPP_ERROR(get_logger(), "%s: invalid or unsupported address.", TAG);
      close(sock_);
      sock_ = -1;
      return false;
    }
    timeval tv_recv{0, 5000};
    timeval tv_send{0, 10000};
    setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv));
    setsockopt(sock_, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send));
    RCLCPP_INFO(get_logger(), "%s: UDP connected.", TAG);
    return true;
  }

  bool send_frame(const std::string & frame)
  {
    const ssize_t sent = sendto(sock_, frame.data(), frame.size(), 0,
                                reinterpret_cast<struct sockaddr *>(&serv_addr_),
                                sizeof(serv_addr_));
    if (sent != static_cast<ssize_t>(frame.size())) {
      RCLCPP_ERROR(get_logger(), "%s: screen send failed: %s", TAG, strerror(errno));
      return false;
    }
    return true;
  }

  void on_qrcode_text(const std_msgs::msg::String::SharedPtr msg)
  {
    if (msg->data == last_qrcode_text_) {
      return;  // ROS 1 suppressed repeats
    }
    last_qrcode_text_ = msg->data;
    for (const auto & frame : framed_datagrams(msg->data)) {
      if (!send_frame(frame)) {
        // Recreate the socket, as ROS 1's udp_init() retry did.
        udp_init();
        return;
      }
    }
  }

  double control_freq_ = 5.0;
  std::string ip_address_;
  int port_ = 26;
  int sock_ = -1;
  struct sockaddr_in serv_addr_ {};
  std::string last_qrcode_text_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr qrcode_text_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<ScreenNode>());
  } catch (const std::exception & err) {
    RCLCPP_FATAL(rclcpp::get_logger(NODE_NAME), "start-up failed: %s", err.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
