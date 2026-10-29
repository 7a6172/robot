// Thin ROS 2 adapter over the vendor's ROS-independent Vanjee driver.
//
// The driver already does the hard part: UDP reception, DIFOP/scan-data protocol, decoding
// and handing back a `ScanData`. This node only (a) configures it from ROS parameters and
// (b) converts `ScanData` into `sensor_msgs/msg/LaserScan`. It deliberately does not fork
// the driver, does not need `vanjee_lidar_msg`, and does not rebuild the vendor's ROS
// wrapper -- the driver's headers are used directly.
//
// The sensor contract is taken from the ROS 1 baseline measured on the robot, not invented:
//   /scan, sensor_msgs/LaserScan, frame `lidar_link`, ~14.03 Hz, 1440 samples,
//   +-pi at ~0.004363323 rad, 0.25-25.0 m, wall-clock timestamps, NaN for no-return.

#include <atomic>
#include <chrono>
#include <cmath>
#include <thread>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <cstring>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>

#include <vanjee_driver/api/lidar_driver.hpp>
#include <vanjee_driver/msg/point_cloud_msg.hpp>
#include <vanjee_driver/msg/scan_data_msg.hpp>

namespace
{

using PointT = vanjee::lidar::PointCloudT<vanjee::lidar::PointXYZI>;
using Driver = vanjee::lidar::LidarDriver<PointT>;

//! Parameters this node needs, read without creating an rclcpp::Node.
/*!
 * The driver must bind its UDP port before the DDS participant exists, because a DDS
 * participant binds a socket on port 7000 in-process (see the phase-08 report) and does so
 * without SO_REUSEADDR, so the LiDAR's own MSOP port could never be bound afterwards.
 * Creating a Node first would therefore make the hardware unusable from the same process.
 */
struct NodeParams {
  std::string lidar_type{"vanjee_718h"};
  std::string host_address{"192.168.110.10"};
  std::string lidar_address{"192.168.110.100"};
  int host_msop_port{7000};
  int lidar_msop_port{5000};
  std::string frame_id{"lidar_link"};
  std::string topic{"scan"};
  double min_distance{0.25};
  double max_distance{25.0};
  bool use_lidar_clock{false};
};

//! Reads ``-p name:=value`` / ``--param name:=value`` pairs from the ROS arguments.
NodeParams parse_params(int argc, char ** argv)
{
  NodeParams p;
  std::map<std::string, std::string> kv;
  for (int i = 1; i + 1 < argc; ++i) {
    const std::string flag(argv[i]);
    if (flag != "-p" && flag != "--param") {
      continue;
    }
    const std::string arg(argv[i + 1]);
    const auto sep = arg.find(":=");
    if (sep == std::string::npos) {
      continue;
    }
    std::string v = arg.substr(sep + 2);
    if (v.size() > 1 && v.front() == '\'' && v.back() == '\'') {
      v = v.substr(1, v.size() - 2);
    }
    kv[arg.substr(0, sep)] = v;
  }
  auto str = [&kv](const char * k, std::string & d) {
      auto it = kv.find(k);
      if (it != kv.end()) { d = it->second; }
    };
  auto num = [&kv](const char * k, auto & d) {
      auto it = kv.find(k);
      if (it != kv.end()) {
        try { d = static_cast<std::decay_t<decltype(d)>>(std::stod(it->second)); } catch (...) {}
      }
    };
  str("lidar_type", p.lidar_type);
  str("host_address", p.host_address);
  str("lidar_address", p.lidar_address);
  str("frame_id", p.frame_id);
  str("topic", p.topic);
  num("host_msop_port", p.host_msop_port);
  num("lidar_msop_port", p.lidar_msop_port);
  num("min_distance", p.min_distance);
  num("max_distance", p.max_distance);
  {
    bool v = p.use_lidar_clock;
    num("use_lidar_clock", v);
    p.use_lidar_clock = v;
  }
  return p;
}

//! Fills the driver's own parameter struct from ROS parameters.
/*!
 * The driver's public API takes a ``WJDriverParam`` directly, so no YAML document and no
 * yaml-cpp dependency are needed. Defaults below are the values verified on the robot.
 */
vanjee::lidar::WJDriverParam build_param(const NodeParams & p)
{
  vanjee::lidar::WJDriverParam param;
  param.lidar_type = vanjee::lidar::LidarType::vanjee_718h;
  param.input_type = vanjee::lidar::InputType::ONLINE_LIDAR;

  param.input_param.connect_type = 1;  // UDP
  param.input_param.host_msop_port = static_cast<uint16_t>(p.host_msop_port);
  param.input_param.lidar_msop_port = static_cast<uint16_t>(p.lidar_msop_port);
  param.input_param.host_address = p.host_address;
  param.input_param.lidar_address = p.lidar_address;
  param.input_param.group_address = "0.0.0.0";

  // The device broadcasts to 0.0.0.0:0 until the driver configures it, so waiting for
  // DIFOP is required rather than optional.
  param.decoder_param.wait_for_difop = true;
  param.decoder_param.min_distance = static_cast<float>(p.min_distance);
  param.decoder_param.max_distance = static_cast<float>(p.max_distance);
  param.decoder_param.start_angle = 0.0f;
  param.decoder_param.end_angle = 360.0f;
  param.decoder_param.use_lidar_clock = p.use_lidar_clock;
  param.decoder_param.dense_points = false;
  param.decoder_param.ts_first_point = true;
  param.decoder_param.publish_mode = 0;
  param.decoder_param.config_from_file = false;
  return param;
}

}  // namespace

//! Publishes the scans the driver has already produced.
/*!
 * The driver is started before this node exists (see main), so its callbacks cannot touch
 * ROS. They hand finished `ScanData` objects to this class through a bounded queue, and a
 * timer drains that queue. Bounded on purpose: an unbounded queue turns a stuck publisher
 * into an out-of-memory kill.
 */
class ScanBridge {
public:
  void push(const std::shared_ptr<vanjee::lidar::ScanData> & data)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.size() >= kMaxQueued) {
      queue_.pop_front();
      ++dropped_;
    }
    queue_.push_back(data);
  }

  std::shared_ptr<vanjee::lidar::ScanData> pop()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.empty()) {
      return nullptr;
    }
    auto data = queue_.front();
    queue_.pop_front();
    return data;
  }

  size_t dropped() const { return dropped_; }

private:
  static constexpr size_t kMaxQueued = 16;
  mutable std::mutex mutex_;
  std::deque<std::shared_ptr<vanjee::lidar::ScanData>> queue_;
  size_t dropped_{0};
};

class VanjeeScanNode : public rclcpp::Node
{
public:
  VanjeeScanNode(const NodeParams & params, std::shared_ptr<ScanBridge> bridge)
  : rclcpp::Node("vanjee_lidar_node"), params_(params), bridge_(std::move(bridge))
  {
    publisher_ = create_publisher<sensor_msgs::msg::LaserScan>(
      params_.topic, rclcpp::QoS(10));
    timer_ = create_wall_timer(std::chrono::milliseconds(5), [this]() { drain(); });
    RCLCPP_INFO(get_logger(), "vanjee scan node up: %s:%d -> %s (frame %s)",
                params_.lidar_address.c_str(), params_.lidar_msop_port,
                params_.topic.c_str(), params_.frame_id.c_str());
  }

private:
  void drain()
  {
    while (auto data = bridge_->pop()) {
      publish(*data);
    }
  }

  void publish(const vanjee::lidar::ScanData & data)
  {
    if (data.ranges.empty()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "empty scan discarded");
      return;
    }
    sensor_msgs::msg::LaserScan msg;
    // The driver reports angles in DEGREES (its own ROS conversion divides by 180 and
    // multiplies by pi); do the same here rather than assuming radians.
    msg.angle_min = static_cast<float>(data.angle_min / 180.0 * M_PI);
    msg.angle_max = static_cast<float>(data.angle_max / 180.0 * M_PI);
    msg.angle_increment = static_cast<float>(data.angle_increment / 180.0 * M_PI);
    msg.time_increment = data.time_increment;
    msg.scan_time = data.scan_time;
    msg.range_min = data.range_min;
    msg.range_max = data.range_max;
    msg.ranges = data.ranges;
    msg.intensities = data.intensities;

    if (params_.use_lidar_clock) {
      const auto sec = static_cast<int32_t>(data.timestamp);
      msg.header.stamp.sec = sec;
      msg.header.stamp.nanosec =
        static_cast<uint32_t>((data.timestamp - static_cast<double>(sec)) * 1e9);
    } else {
      // Wall clock, matching the ROS 1 baseline (use_lidar_clock: false).
      msg.header.stamp = now();
    }
    msg.header.frame_id = params_.frame_id;
    publisher_->publish(msg);

    if (++count_ == 1) {
      RCLCPP_INFO(get_logger(), "first scan published (%zu samples)", msg.ranges.size());
    } else if (count_ % 200 == 0 && bridge_->dropped() != last_dropped_) {
      RCLCPP_WARN(get_logger(), "%zu scans dropped while publishing", bridge_->dropped());
      last_dropped_ = bridge_->dropped();
    }
  }

  NodeParams params_;
  std::shared_ptr<ScanBridge> bridge_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
  size_t count_{0};
  size_t last_dropped_{0};
};

//! Reports whether a UDP port can be bound, so a conflict fails loudly and immediately.
/*!
 * The driver retries its bind forever on failure, which from the outside looks like a hang
 * rather than an error. Checking first turns that into one actionable message.
 */
std::string port_conflict(const std::string & host, int port)
{
  const int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) {
    return "socket() failed";
  }
  // Deliberately WITHOUT SO_REUSEADDR: with it, a second listener on the same address and
  // port also succeeds and silently starves the first, so a duplicate driver would look
  // healthy while delivering nothing to the original. Binding strictly is the only way to
  // answer "is this port already owned?".
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<uint16_t>(port));
  addr.sin_addr.s_addr = INADDR_ANY;
  if (host != "0.0.0.0") {
    ::inet_pton(AF_INET, host.c_str(), &addr.sin_addr);
  }
  std::string err;
  if (::bind(fd, reinterpret_cast<struct sockaddr *>(&addr), sizeof(addr)) < 0) {
    err = std::string("cannot bind ") + host + ":" + std::to_string(port) + ": " +
          std::strerror(errno) +
          " (another process, or a DDS participant, already owns it; find it with "
          "`ss -lunp | grep :" + std::to_string(port) + "`)";
  }
  ::close(fd);
  return err;
}

int main(int argc, char ** argv)
{
  const NodeParams params = parse_params(argc, argv);

  // Bind the LiDAR's MSOP port before any DDS participant exists: a DDS participant takes
  // a socket on port 7000 in-process, which is exactly the LiDAR's MSOP port, and it does
  // not set SO_REUSEADDR, so binding afterwards can never succeed.
  if (const std::string err = port_conflict(params.host_address, params.host_msop_port);
      !err.empty())
  {
    std::cerr << "[FATAL] " << err << std::endl;
    // launch restarts a dead node immediately, so exiting straight away turns one unrecoverable
    // conflict into a wall of identical lines (19 of them were counted in under a second). A short
    // pause keeps the restart useful for a genuine hardware hiccup while leaving the log readable.
    std::this_thread::sleep_for(std::chrono::seconds(2));
    return 1;
  }

  auto bridge = std::make_shared<ScanBridge>();
  auto driver = std::make_shared<Driver>();
  driver->regScanDataCallback(
    []() { return std::make_shared<vanjee::lidar::ScanData>(); },
    [bridge](std::shared_ptr<vanjee::lidar::ScanData> data) { bridge->push(data); });
  // The driver invokes these unconditionally while running, so they must be registered even
  // though only scan data is published (unregistered ones aborted with bad_function_call).
  driver->regPointCloudCallback(
    []() { return std::make_shared<PointT>(); },
    [](std::shared_ptr<PointT>) {});
  driver->regPacketCallback([](const vanjee::lidar::Packet &) {});
  driver->regImuPacketCallback(
    []() { return std::make_shared<vanjee::lidar::ImuPacket>(); },
    [](std::shared_ptr<vanjee::lidar::ImuPacket>) {});
  driver->regExceptionCallback([](const vanjee::lidar::Error & err) {
      std::cerr << "[driver] error " << err.error_code << ": " << err.toString() << std::endl;
    });

  const auto param = build_param(params);
  if (!driver->init(param)) {
    std::cerr << "[FATAL] vanjee driver failed to initialise" << std::endl;
    return 1;
  }
  if (!driver->start()) {
    std::cerr << "[FATAL] vanjee driver failed to start" << std::endl;
    return 1;
  }

  // Only now create the ROS node, so its DDS participant cannot take the LiDAR's port.
  rclcpp::init(argc, argv);
  int rc = 0;
  try {
    auto node = std::make_shared<VanjeeScanNode>(params, bridge);
    rclcpp::spin(node);
  } catch (const std::exception & err) {
    std::cerr << "[FATAL] node failed: " << err.what() << std::endl;
    rc = 1;
  }

  // stop() can block while the driver's receive thread is busy, so bound the wait and say
  // so rather than hanging: shutdown must always complete and the reason must be visible.
  std::atomic<bool> stopped{false};
  std::thread stopper([&driver, &stopped]() {
    driver->stop();
    stopped = true;
  });
  for (int i = 0; i < 30 && !stopped; ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  if (stopped) {
    stopper.join();
  } else {
    std::cerr << "[WARN] driver did not stop within 3 s; abandoning its receive thread"
              << std::endl;
    stopper.detach();
  }
  rclcpp::shutdown();
  return rc;
}
