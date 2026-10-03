/**
 * @author
 *   ZHANG Muhua
 * @affiliation
 *   Southwest Jiaotong University
 * @license
 *   GPL-3.0 License
 *
 * ROS 2 Jazzy port by zar (zar@my.swjtu.edu.cn)
 */

#include <rclcpp/rclcpp.hpp>
#include <tf2/utils.hpp>
#include <tf2/LinearMath/Transform.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <algorithm>
#include <limits>
#include <angles/angles.h>
#include <std_msgs/msg/empty.hpp>
#include <std_srvs/srv/empty.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <common/common_state_code.h>
#include <utils/2d/relocalization_2d.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/transform_broadcaster.h>
#include <relocalization_toolbox_msgs/srv/initial_pose_request.hpp>
#include <relocalization_toolbox_msgs/srv/relocalization_request.hpp>

#define NODE_NAME "relocalization_2d_handler"
#define TAG "2D Global Relocalization"

using namespace std;

// general parameters
bool publish_init_pose_topic;
bool call_init_pose_request;

string map_frame;
string base_frame;
string lidar_frame;
bool prefetch_map_from_topic;
bool lidar_reverted;
int lidar_sampling_step;

bool enable_visualization;

bool use_reachability_sampling;
float rrt_min_expand_dist, rrt_max_expand_dist;
int reachability_sampling_duration;

float fit_score_threshold_min, fit_score_threshold_max;
float angle_search_step;
int area_batch_proc_number;
int area_candidate_number;
float min_dist_to_obstacle;

// likelihood field model parameters
float sigma_hit;
float z_hit;
float z_rand;
float max_tolerance_dist;

// map-related parameters
int map_free_threshold;
int map_occupied_threshold;

// submap partitioning parameters
float sensing_radius;
float anchor_point_min_dist;

// ICP matching parameters
float max_correspondence_distance;
float transformation_epsilon;
float euclidean_fitness_epsilon;
int max_iterations;

// node and tf components
rclcpp::Node::SharedPtr node;
unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster;
unique_ptr<tf2_ros::Buffer> tf_buffer;
geometry_msgs::msg::TransformStamped tf_lidar_to_base;

// relocalization services
rclcpp::Service<relocalization_toolbox_msgs::srv::RelocalizationRequest>::SharedPtr relocalization_server;
rclcpp::Service<std_srvs::srv::Empty>::SharedPtr relocalization_simple_server;
// relocalization client and publisher
rclcpp::Client<relocalization_toolbox_msgs::srv::InitialPoseRequest>::SharedPtr set_init_pose_client;
rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr init_pose_pub;

// relocalization core system
unique_ptr<relocalization_2d::relocalization_2d> relocalization_2d_instance;

// topic data
sensor_msgs::msg::LaserScan scan_data;
nav_msgs::msg::OccupancyGrid map_data;
bool map_data_received = false;

// 等待并接收一条指定话题的消息（等价于 ROS 1 的 ros::topic::waitForMessage）
template <typename MsgT>
typename MsgT::SharedPtr wait_for_message_once(const string &topic, const rclcpp::QoS &qos, const double &timeout_secs)
{
    string node_name = "wait_for_message_node";
    for (const char &c : topic)
    {
        if (isalnum(c))
        {
            node_name += c;
        }
    }

    auto wait_node = std::make_shared<rclcpp::Node>(node_name);

    typename MsgT::SharedPtr received;
    auto sub = wait_node->create_subscription<MsgT>(
        topic, qos, [&](typename MsgT::SharedPtr msg) { received = msg; });

    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(wait_node);

    auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(timeout_secs);
    while (rclcpp::ok() && !received && std::chrono::steady_clock::now() < deadline)
    {
        executor.spin_once(std::chrono::milliseconds(50));
    }

    executor.remove_node(wait_node);

    return received;
}

// callback functions
void relocalization_request_callback(const std::shared_ptr<relocalization_toolbox_msgs::srv::RelocalizationRequest::Request> req,
                                     std::shared_ptr<relocalization_toolbox_msgs::srv::RelocalizationRequest::Response> res)
{
    // get current scan
    auto scan_data_ptr = wait_for_message_once<sensor_msgs::msg::LaserScan>("scan", rclcpp::SensorDataQoS(), 2.0);

    if (scan_data_ptr)
    {
        scan_data = *scan_data_ptr;
        scan_data.header.frame_id = lidar_frame;

        // check request mode
        if (req->mode == req->MODE_MAP_FROM_FILE)
        {
            // load map from file
            auto data_loaded = load_map_2d(req->path, req->name, map_frame);
            map_data_received = get<0>(data_loaded);

            if (map_data_received)
            {
                map_data = get<1>(data_loaded);
            }
        }
        else if (req->mode == req->MODE_MAP_FROM_TOPIC)
        {
            // load map from topic
            auto map_data_ptr = wait_for_message_once<nav_msgs::msg::OccupancyGrid>(
                "map", rclcpp::QoS(1).reliable().transient_local(), 5.0);

            if (map_data_ptr)
            {
                map_data = *map_data_ptr;
                map_data.header.frame_id = map_frame;
                map_data_received = true;
            }
        }
        else
        {
            RCLCPP_ERROR(rclcpp::get_logger("relocalization_2d"), "%s: Request failed, invalid map input mode.", TAG);

            res->result = CMD_RESPONSE_ERROR;
        }

        if (map_data_received)
        {
            // Start to relocalize
            auto reloc_result = relocalization_2d_instance->relocalize(scan_data, lidar_reverted, lidar_sampling_step, map_data);

            if (get<0>(reloc_result))
            {
                res->result = CMD_RESPONSE_OK;
                res->score = get<1>(reloc_result);

                // get transformations
                tf2::Transform tf_map_lidar, tf_lidar_base, tf_map_base;
                tf2::fromMsg(get<2>(reloc_result).transform, tf_map_lidar);
                tf2::fromMsg(tf_lidar_to_base.transform, tf_lidar_base);
                tf_map_base = tf_map_lidar * tf_lidar_base;
                geometry_msgs::msg::TransformStamped tf_map_to_base;
                tf_map_to_base.header.stamp = get<2>(reloc_result).header.stamp;
                tf_map_to_base.header.frame_id = map_frame;
                tf_map_to_base.child_frame_id = base_frame;
                tf_map_to_base.transform = tf2::toMsg(tf_map_base);

                res->tf_map_to_base = tf_map_to_base;

                geometry_msgs::msg::PoseWithCovarianceStamped init_pose;
                init_pose.header.stamp = node->now();
                init_pose.header.frame_id = map_frame;
                init_pose.pose.pose.position.x = res->tf_map_to_base.transform.translation.x;
                init_pose.pose.pose.position.y = res->tf_map_to_base.transform.translation.y;
                init_pose.pose.pose.position.z = res->tf_map_to_base.transform.translation.z;
                init_pose.pose.pose.orientation = res->tf_map_to_base.transform.rotation;

                if (publish_init_pose_topic)
                {
                    init_pose_pub->publish(init_pose);
                }

                if (call_init_pose_request)
                {
                    auto init_pose_request = std::make_shared<relocalization_toolbox_msgs::srv::InitialPoseRequest::Request>();
                    init_pose_request->pose = init_pose;

                    auto future = set_init_pose_client->async_send_request(init_pose_request);

                    if (future.wait_for(std::chrono::seconds(5)) != std::future_status::ready)
                    {
                        RCLCPP_WARN(rclcpp::get_logger("relocalization_2d"), "%s: Initial pose request timed out.", TAG);
                    }
                }
            }
            else
            {
                RCLCPP_ERROR(rclcpp::get_logger("relocalization_2d"), "%s: Relocalization failed. Score below threshold.", TAG);

                res->result = CMD_RESPONSE_ERROR;
            }
        }
        else
        {
            RCLCPP_ERROR(rclcpp::get_logger("relocalization_2d"), "%s: Request failed. No map data available.", TAG);

            res->result = CMD_RESPONSE_ERROR;
        }
    }
    else
    {
        RCLCPP_ERROR(rclcpp::get_logger("relocalization_2d"), "%s: Request failed. No scan data received.", TAG);

        res->result = CMD_RESPONSE_ERROR;
    }
}

void relocalization_simple_request_callback(const std::shared_ptr<std_srvs::srv::Empty::Request> req,
                                            std::shared_ptr<std_srvs::srv::Empty::Response> res)
{
    (void)req;
    (void)res;

    auto srv_request = std::make_shared<relocalization_toolbox_msgs::srv::RelocalizationRequest::Request>();
    auto srv_response = std::make_shared<relocalization_toolbox_msgs::srv::RelocalizationRequest::Response>();

    srv_request->mode = srv_request->MODE_MAP_FROM_TOPIC;

    relocalization_request_callback(srv_request, srv_response);
}

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);

    setlocale(LC_CTYPE, "en_US.utf8");

    RCLCPP_INFO(rclcpp::get_logger("relocalization_2d"), "%s: Node started.", TAG);

    node = rclcpp::Node::make_shared(NODE_NAME);

    // Load parameters
    publish_init_pose_topic = node->declare_parameter<bool>("relocalization_2d.publish_init_pose_topic", false);
    call_init_pose_request = node->declare_parameter<bool>("relocalization_2d.call_init_pose_request", true);

    map_frame = node->declare_parameter<string>("relocalization_2d.map_frame", "map");
    base_frame = node->declare_parameter<string>("relocalization_2d.base_frame", "base_link");
    lidar_frame = node->declare_parameter<string>("relocalization_2d.lidar_frame", "lidar_link");

    prefetch_map_from_topic = node->declare_parameter<bool>("relocalization_2d.prefetch_map_from_topic", true);

    lidar_reverted = node->declare_parameter<bool>("relocalization_2d.lidar_reverted", true);

    lidar_sampling_step = node->declare_parameter<int>("relocalization_2d.lidar_sampling_step", 4);

    enable_visualization = node->declare_parameter<bool>("relocalization_2d.enable_visualization", true);

    use_reachability_sampling = node->declare_parameter<bool>("relocalization_2d.use_reachability_sampling", false);
    rrt_min_expand_dist = static_cast<float>(node->declare_parameter<double>("relocalization_2d.rrt_min_expand_dist", 0.5));
    rrt_max_expand_dist = static_cast<float>(node->declare_parameter<double>("relocalization_2d.rrt_max_expand_dist", 1.0));
    reachability_sampling_duration = node->declare_parameter<int>("relocalization_2d.reachability_sampling_duration", 5);

    fit_score_threshold_max = static_cast<float>(node->declare_parameter<double>("relocalization_2d.fit_score_threshold_max", 0.9));
    fit_score_threshold_min = static_cast<float>(node->declare_parameter<double>("relocalization_2d.fit_score_threshold_min", 0.8));
    angle_search_step = static_cast<float>(node->declare_parameter<double>("relocalization_2d.angle_search_step", 10.0 * M_PI / 180.0));
    area_batch_proc_number = node->declare_parameter<int>("relocalization_2d.area_batch_proc_number", 500);
    area_candidate_number = node->declare_parameter<int>("relocalization_2d.area_candidate_number", 10);
    min_dist_to_obstacle = static_cast<float>(node->declare_parameter<double>("relocalization_2d.min_dist_to_obstacle", 0.4));

    sigma_hit = static_cast<float>(node->declare_parameter<double>("relocalization_2d.sigma_hit", 0.2));
    z_hit = static_cast<float>(node->declare_parameter<double>("relocalization_2d.z_hit", 1.0));
    z_rand = static_cast<float>(node->declare_parameter<double>("relocalization_2d.z_rand", 0.0));
    max_tolerance_dist = static_cast<float>(node->declare_parameter<double>("relocalization_2d.max_tolerance_dist", 1.0));

    map_free_threshold = node->declare_parameter<int>("relocalization_2d.map_free_threshold", 30);
    map_occupied_threshold = node->declare_parameter<int>("relocalization_2d.map_occupied_threshold", 55);

    sensing_radius = static_cast<float>(node->declare_parameter<double>("relocalization_2d.sensing_radius", 15.0));
    anchor_point_min_dist = static_cast<float>(node->declare_parameter<double>("relocalization_2d.anchor_point_min_dist", 3.0));

    max_correspondence_distance = static_cast<float>(node->declare_parameter<double>("relocalization_2d.max_correspondence_distance", 1.0));
    transformation_epsilon = static_cast<float>(node->declare_parameter<double>("relocalization_2d.transformation_epsilon", 1e-6));
    euclidean_fitness_epsilon = static_cast<float>(node->declare_parameter<double>("relocalization_2d.euclidean_fitness_epsilon", 1e-5));
    max_iterations = node->declare_parameter<int>("relocalization_2d.max_iterations", 50);

    // tf setup
    tf_broadcaster = unique_ptr<tf2_ros::TransformBroadcaster>(new tf2_ros::TransformBroadcaster(node));
    tf_buffer = unique_ptr<tf2_ros::Buffer>(new tf2_ros::Buffer(node->get_clock()));
    tf2_ros::TransformListener tf_listener(*tf_buffer);

    // initialize relocalization instance
    relocalization_2d_instance = unique_ptr<relocalization_2d::relocalization_2d>(
        new relocalization_2d::relocalization_2d(
            node,
            enable_visualization, use_reachability_sampling,
            rrt_min_expand_dist, rrt_max_expand_dist, reachability_sampling_duration,
            fit_score_threshold_min, fit_score_threshold_max, angle_search_step,
            area_batch_proc_number, area_candidate_number, min_dist_to_obstacle,
            sigma_hit, z_hit, z_rand, max_tolerance_dist,
            map_free_threshold, map_occupied_threshold,
            sensing_radius, anchor_point_min_dist,
            max_correspondence_distance, transformation_epsilon, euclidean_fitness_epsilon, max_iterations));

    if (prefetch_map_from_topic)
    {
        RCLCPP_INFO(rclcpp::get_logger("relocalization_2d"), "%s: Attempting to fetch map data...", TAG);

        auto map_data_ptr = wait_for_message_once<nav_msgs::msg::OccupancyGrid>(
            "map", rclcpp::QoS(1).reliable().transient_local(), 30.0);

        if (map_data_ptr)
        {
            RCLCPP_INFO(rclcpp::get_logger("relocalization_2d"), "%s: Map data received successfully.", TAG);

            map_data = *map_data_ptr;
            map_data.header.frame_id = map_frame;
            map_data_received = true;

            relocalization_2d_instance->set_map(map_data);
        }
        else
        {
            RCLCPP_WARN(rclcpp::get_logger("relocalization_2d"), "%s: No map data. Will fetch when service is called.", TAG);
        }
    }

    // 单独的可重入回调组，避免服务回调内嵌套等待服务响应时产生执行器死锁
    auto reentrant_group = node->create_callback_group(rclcpp::CallbackGroupType::Reentrant);

    // initialize services and publishers
    relocalization_server = node->create_service<relocalization_toolbox_msgs::srv::RelocalizationRequest>(
        "relocalization_request", relocalization_request_callback);
    relocalization_simple_server = node->create_service<std_srvs::srv::Empty>(
        "relocalization_simple_request", relocalization_simple_request_callback);
    set_init_pose_client = node->create_client<relocalization_toolbox_msgs::srv::InitialPoseRequest>(
        "set_init_pose_request", rclcpp::ServicesQoS(), reentrant_group);
    init_pose_pub = node->create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("initialpose", 1);

    RCLCPP_INFO(rclcpp::get_logger("relocalization_2d"), "%s: Waiting for static transform from %s to %s...", TAG, lidar_frame.c_str(), base_frame.c_str());

    try
    {
        tf_lidar_to_base = tf_buffer->lookupTransform(
            lidar_frame,
            base_frame,
            tf2::TimePointZero,
            std::chrono::seconds(10));
    }
    catch (tf2::TransformException &ex)
    {
        RCLCPP_ERROR(rclcpp::get_logger("relocalization_2d"), "%s: Failed to retrieve transform from %s to %s.", TAG,
                     lidar_frame.c_str(), base_frame.c_str());

        rclcpp::shutdown();

        return 0;
    }

    RCLCPP_INFO(rclcpp::get_logger("relocalization_2d"), "%s: Ready and listening for service requests.", TAG);

    // 多线程执行器：服务回调内部会同步等待话题消息与嵌套服务响应，
    // 需要其他线程继续处理订阅与客户端响应（等价于 ROS 1 的默认行为）
    rclcpp::executors::MultiThreadedExecutor executor;
    executor.add_node(node);
    executor.spin();

    if (relocalization_2d_instance)
    {
        relocalization_2d_instance.reset();
    }

    rclcpp::shutdown();

    return 0;
}
