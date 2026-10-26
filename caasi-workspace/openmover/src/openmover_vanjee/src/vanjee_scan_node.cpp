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
#include <memory>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>

#include <vanjee_driver/api/lidar_driver.hpp>
#include <vanjee_driver/msg/point_cloud_msg.hpp>
#include <vanjee_driver/msg/scan_data_msg.hpp>

namespace
{

using PointT = vanjee::lidar::PointCloudT<vanjee::lidar::PointXYZI>;
using Driver = vanjee::lidar::LidarDriver<PointT>;

//! Fills the driver's own parameter struct from ROS parameters.
/*!
 * The driver's public API takes a ``WJDriverParam`` directly, so no YAML document and no
 * yaml-cpp dependency are needed. Defaults below are the values verified on the robot.
 */
vanjee::lidar::WJDriverParam build_param(const rclcpp::Node & node)
{
  vanjee::lidar::WJDriverParam param;
  param.lidar_type = vanjee::lidar::LidarType::vanjee_718h;
  param.input_type = vanjee::lidar::InputType::ONLINE_LIDAR;

  param.input_param.connect_type = 1;  // UDP
  param.input_param.host_msop_port =
    static_cast<uint16_t>(node.get_parameter("host_msop_port").as_int());
  param.input_param.lidar_msop_port =
    static_cast<uint16_t>(node.get_parameter("lidar_msop_port").as_int());
  param.input_param.host_address = node.get_parameter("host_address").as_string();
  param.input_param.lidar_address = node.get_parameter("lidar_address").as_string();
  param.input_param.group_address = "0.0.0.0";

  // The device broadcasts to 0.0.0.0:0 until the driver configures it, so waiting for
  // DIFOP is required rather than optional.
  param.decoder_param.wait_for_difop = true;
  param.decoder_param.min_distance =
    static_cast<float>(node.get_parameter("min_distance").as_double());
  param.decoder_param.max_distance =
    static_cast<float>(node.get_parameter("max_distance").as_double());
  param.decoder_param.start_angle = 0.0f;
  param.decoder_param.end_angle = 360.0f;
  param.decoder_param.use_lidar_clock = node.get_parameter("use_lidar_clock").as_bool();
  param.decoder_param.dense_points = false;
  param.decoder_param.ts_first_point = true;
  param.decoder_param.publish_mode = 0;
  param.decoder_param.config_from_file = false;
  return param;
}

}  // namespace

class VanjeeScanNode : public rclcpp::Node
{
public:
  VanjeeScanNode() : rclcpp::Node("vanjee_lidar_node")
  {
    // Defaults mirror the verified hardware configuration measured from the robot.
    declare_parameter("lidar_type", "vanjee_718h");
    declare_parameter("host_address", "192.168.110.10");
    declare_parameter("lidar_address", "192.168.110.100");
    declare_parameter("host_msop_port", 7000);
    declare_parameter("lidar_msop_port", 5000);
    declare_parameter("frame_id", "lidar_link");
    declare_parameter("topic", "scan");
    declare_parameter("min_distance", 0.25);
    declare_parameter("max_distance", 25.0);
    declare_parameter("use_lidar_clock", false);

    const std::string topic = get_parameter("topic").as_string();
    // Reliable, depth 10: the ROS 1 baseline had no such distinction (effectively
    // reliable) and downstream consumers (laser filters, costmaps) subscribe reliably.
    // SensorDataQoS here silently dropped every message for such a subscriber.
    publisher_ = create_publisher<sensor_msgs::msg::LaserScan>(topic, rclcpp::QoS(10));

    driver_ = std::make_shared<Driver>();
    driver_->regScanDataCallback(
      []() { return std::make_shared<vanjee::lidar::ScanData>(); },
      [this](std::shared_ptr<vanjee::lidar::ScanData> data) { onScan(data); });
    // The driver invokes these unconditionally while running, so they must be registered
    // even though this node only publishes scan data (found as bad_function_call at
    // startup on the robot). Clouds are drained and discarded.
    driver_->regPointCloudCallback(
      []() { return std::make_shared<PointT>(); },
      [](std::shared_ptr<PointT>) {});
    driver_->regPacketCallback([](const vanjee::lidar::Packet &) {});
    driver_->regImuPacketCallback(
      []() { return std::make_shared<vanjee::lidar::ImuPacket>(); },
      [](std::shared_ptr<vanjee::lidar::ImuPacket>) {});
    driver_->regExceptionCallback([this](const vanjee::lidar::Error & err) {
      // Error carries a code and a message; throttled so a persistent fault cannot flood.
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000,
                            "driver error (code %d): %s", err.error_code,
                            err.toString().c_str());
    });

    const auto param = build_param(*this);
    if (!driver_->init(param)) {
      RCLCPP_FATAL(get_logger(), "driver failed to initialise; refusing to publish");
      throw std::runtime_error("vanjee driver init failed");
    }
    running_ = driver_->start();
    if (!running_) {
      RCLCPP_FATAL(get_logger(), "driver failed to start");
      throw std::runtime_error("vanjee driver start failed");
    }
    RCLCPP_INFO(get_logger(), "vanjee scan node up: %s -> %s (frame %s)",
                get_parameter("lidar_address").as_string().c_str(), topic.c_str(),
                get_parameter("frame_id").as_string().c_str());
  }

  ~VanjeeScanNode() override
  {
    // stop() can block indefinitely while the driver's receive thread is retrying a socket
    // bind, which made the process ignore both SIGTERM and SIGINT (measured on the robot:
    // still alive after 8 s, then required SIGKILL). Bound the wait and say so rather than
    // hanging, so shutdown always completes and the reason is recorded in the log.
    if (!driver_ || !running_) {
      return;
    }
    std::atomic<bool> done{false};
    std::thread stopper([this, &done]() {
      driver_->stop();
      done = true;
    });
    for (int i = 0; i < 30 && !done; ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (done) {
      stopper.join();
    } else {
      RCLCPP_WARN(get_logger(),
                  "driver did not stop within 3 s; abandoning the receive thread so "
                  "shutdown can complete");
      stopper.detach();
    }
  }

private:
  void onScan(const std::shared_ptr<vanjee::lidar::ScanData> & data)
  {
    if (!data || data->ranges.empty()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "empty scan discarded");
      return;
    }

    sensor_msgs::msg::LaserScan msg;
    // The driver reports angles in DEGREES (its own ROS conversion divides by 180 and
    // multiplies by pi); do the same here rather than assuming radians.
    msg.angle_min = static_cast<float>(data->angle_min / 180.0 * M_PI);
    msg.angle_max = static_cast<float>(data->angle_max / 180.0 * M_PI);
    msg.angle_increment = static_cast<float>(data->angle_increment / 180.0 * M_PI);
    msg.time_increment = data->time_increment;
    msg.scan_time = data->scan_time;
    msg.range_min = data->range_min;
    msg.range_max = data->range_max;
    msg.ranges = data->ranges;
    msg.intensities = data->intensities;

    if (get_parameter("use_lidar_clock").as_bool()) {
      const auto sec = static_cast<int32_t>(data->timestamp);
      msg.header.stamp.sec = sec;
      msg.header.stamp.nanosec =
        static_cast<uint32_t>((data->timestamp - static_cast<double>(sec)) * 1e9);
    } else {
      // Wall clock, matching the ROS 1 baseline (use_lidar_clock: false).
      msg.header.stamp = now();
    }
    msg.header.frame_id = get_parameter("frame_id").as_string();

    publisher_->publish(msg);
    ++count_;
    if (count_ == 1) {
      RCLCPP_INFO(get_logger(), "first scan published (%zu samples)", msg.ranges.size());
    }
  }

  std::shared_ptr<Driver> driver_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr publisher_;
  bool running_{false};
  size_t count_{0};
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<VanjeeScanNode>());
  } catch (const std::exception & err) {
    RCLCPP_FATAL(rclcpp::get_logger("vanjee_lidar_node"), "startup failed: %s", err.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
