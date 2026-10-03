// ROS 2 port of ira_laser_tools laserscan_multi_merger.
//
// Merges multiple LaserScan sources into a single scan: each incoming scan is
// projected to a point cloud and transformed into `destination_frame`; once
// every subscribed topic has delivered a scan, the clouds are merged and both
// a PointCloud2 and a binned LaserScan are published.
//
// Faithful to the ROS 1 implementation (same parameter names/defaults, same
// merging/binning behavior) but drops the PCL dependency.

#include <algorithm>
#include <cmath>
#include <iterator>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "laser_geometry/laser_geometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"
#include "tf2/exceptions.h"
#include "tf2_ros/buffer.h"
#include "tf2_ros/transform_listener.h"

class LaserscanMerger : public rclcpp::Node
{
public:
    LaserscanMerger() : Node("laserscan_multi_merger")
    {
        declare_parameter<std::string>("destination_frame", "cart_frame");
        declare_parameter<std::string>("cloud_destination_topic", "/merged_cloud");
        declare_parameter<std::string>("scan_destination_topic", "/scan_multi");
        declare_parameter<std::string>("laserscan_topics", "");
        declare_parameter<double>("angle_min", -2.36);
        declare_parameter<double>("angle_max", 2.36);
        declare_parameter<double>("angle_increment", 0.0058);
        declare_parameter<double>("time_increment", 0.0);
        declare_parameter<double>("scan_time", 0.0333333);
        declare_parameter<double>("range_min", 0.45);
        declare_parameter<double>("range_max", 25.0);

        destination_frame = get_parameter("destination_frame").as_string();
        cloud_destination_topic = get_parameter("cloud_destination_topic").as_string();
        scan_destination_topic = get_parameter("scan_destination_topic").as_string();
        const std::string laserscan_topics = get_parameter("laserscan_topics").as_string();
        angle_min = get_parameter("angle_min").as_double();
        angle_max = get_parameter("angle_max").as_double();
        angle_increment = get_parameter("angle_increment").as_double();
        time_increment = get_parameter("time_increment").as_double();
        scan_time = get_parameter("scan_time").as_double();
        range_min = get_parameter("range_min").as_double();
        range_max = get_parameter("range_max").as_double();

        tf_buffer = std::make_unique<tf2_ros::Buffer>(get_clock());
        tf_listener = std::make_unique<tf2_ros::TransformListener>(*tf_buffer);

        // Parse the space separated topic list (sorted + unique as in ROS 1).
        std::istringstream iss(laserscan_topics);
        std::set<std::string> tokens(std::istream_iterator<std::string>{iss},
                                     std::istream_iterator<std::string>());
        input_topics.assign(tokens.begin(), tokens.end());

        clouds.resize(input_topics.size());
        clouds_modified.assign(input_topics.size(), false);
        scan_subscribers.resize(input_topics.size());

        RCLCPP_INFO(get_logger(), "Subscribing to %zu topics", input_topics.size());
        for (size_t i = 0; i < input_topics.size(); ++i)
        {
            RCLCPP_INFO(get_logger(), "  %s", input_topics[i].c_str());
            scan_subscribers[i] = create_subscription<sensor_msgs::msg::LaserScan>(
                input_topics[i], 1,
                [this, i](const sensor_msgs::msg::LaserScan::SharedPtr scan)
                { scanCallback(scan, i); });
        }

        point_cloud_publisher =
            create_publisher<sensor_msgs::msg::PointCloud2>(cloud_destination_topic, 1);
        laser_scan_publisher =
            create_publisher<sensor_msgs::msg::LaserScan>(scan_destination_topic, 1);
    }

private:
    void scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr scan, size_t index)
    {
        sensor_msgs::msg::PointCloud2 cloud;

        try
        {
            // Verify that TF knows how to transform from the received scan
            // frame to the destination frame (1s wait, as in ROS 1).
            if (!tf_buffer->canTransform(destination_frame, scan->header.frame_id,
                                         scan->header.stamp, tf2::durationFromSec(1.0)))
                return;

            projector.transformLaserScanToPointCloud(
                destination_frame, *scan, cloud, *tf_buffer, -1.0,
                laser_geometry::channel_option::Distance);
        }
        catch (tf2::TransformException &ex)
        {
            RCLCPP_WARN(get_logger(), "TF error while merging scans: %s", ex.what());
            return;
        }

        clouds[index] = cloud;
        clouds_modified[index] = true;

        // Go ahead only if all subscribed scans have arrived.
        size_t total_clouds = 0;
        for (bool modified : clouds_modified)
            if (modified)
                total_clouds++;

        if (total_clouds != clouds_modified.size())
            return;

        // All clouds share the laser_geometry layout, so byte concatenation
        // is equivalent to pcl::concatenate here.
        sensor_msgs::msg::PointCloud2 merged_cloud = clouds[0];
        clouds_modified[0] = false;
        for (size_t i = 1; i < clouds.size(); ++i)
        {
            merged_cloud.data.insert(merged_cloud.data.end(),
                                     clouds[i].data.begin(), clouds[i].data.end());
            merged_cloud.width += clouds[i].width;
            clouds_modified[i] = false;
        }
        merged_cloud.row_step = merged_cloud.width * merged_cloud.point_step;

        point_cloud_publisher->publish(merged_cloud);
        pointcloud_to_laserscan(merged_cloud);
    }

    void pointcloud_to_laserscan(const sensor_msgs::msg::PointCloud2 &merged_cloud)
    {
        auto output = std::make_unique<sensor_msgs::msg::LaserScan>();
        output->header = merged_cloud.header;
        output->angle_min = angle_min;
        output->angle_max = angle_max;
        output->angle_increment = angle_increment;
        output->time_increment = time_increment;
        output->scan_time = scan_time;
        output->range_min = range_min;
        output->range_max = range_max;

        const uint32_t ranges_size =
            std::ceil((output->angle_max - output->angle_min) / output->angle_increment);
        output->ranges.assign(ranges_size, std::numeric_limits<float>::infinity());
        output->intensities.assign(ranges_size, 0.0f);

        sensor_msgs::PointCloud2ConstIterator<float> it_x(merged_cloud, "x");
        sensor_msgs::PointCloud2ConstIterator<float> it_y(merged_cloud, "y");
        sensor_msgs::PointCloud2ConstIterator<float> it_z(merged_cloud, "z");

        for (; it_x != it_x.end(); ++it_x, ++it_y, ++it_z)
        {
            const float x = *it_x;
            const float y = *it_y;
            const float z = *it_z;

            if (std::isnan(x) || std::isnan(y) || std::isnan(z))
                continue;

            const double range_sq = y * y + x * x;
            const double range_min_sq = output->range_min * output->range_min;
            if (range_sq < range_min_sq)
                continue;

            const double angle = std::atan2(y, x);
            if (angle < output->angle_min || angle > output->angle_max)
                continue;

            const int index = (angle - output->angle_min) / output->angle_increment;
            if (output->ranges[index] * output->ranges[index] > range_sq)
                output->ranges[index] = std::sqrt(range_sq);
        }

        laser_scan_publisher->publish(std::move(output));
    }

    laser_geometry::LaserProjection projector;
    std::unique_ptr<tf2_ros::Buffer> tf_buffer;
    std::unique_ptr<tf2_ros::TransformListener> tf_listener;

    rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr point_cloud_publisher;
    rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr laser_scan_publisher;
    std::vector<rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr> scan_subscribers;
    std::vector<bool> clouds_modified;

    std::vector<sensor_msgs::msg::PointCloud2> clouds;
    std::vector<std::string> input_topics;

    double angle_min;
    double angle_max;
    double angle_increment;
    double time_increment;
    double scan_time;
    double range_min;
    double range_max;

    std::string destination_frame;
    std::string cloud_destination_topic;
    std::string scan_destination_topic;
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<LaserscanMerger>());
    rclcpp::shutdown();
    return 0;
}
