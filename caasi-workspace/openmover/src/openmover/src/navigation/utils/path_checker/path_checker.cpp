#include <navigation/utils/path_checker/path_checker.h>
#include <openmover/topic_utils.hpp>

path_checker::path_checker(rclcpp::Node *node) : node_(node)
{
    if (node_)
    {
        visual_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("visual_marker_array", 1);
        path_with_orientation_pub_ = node_->create_publisher<nav_msgs::msg::Path>("path_with_orientation", 1);
    }
}

path_checker::~path_checker()
{
    std::cout << "path checker stopped." << std::endl;
}

vector<point_with_collision_marker> path_checker::check(nav_msgs::msg::Path path,
                                                        geometry_msgs::msg::Polygon &footprint,
                                                        float stop_distance,
                                                        float obstacle_detection_area_padding_ratio,
                                                        int narrow_section_padding,
                                                        int sampling_ratio)
{
    geometry_msgs::msg::PoseStamped pose_default;
    pose_default.pose.orientation = quaternion_msg_from_yaw(0);

    vector<point_with_collision_marker> ret(path.poses.size(),
                                            point_with_collision_marker{
                                                .mode_forward_drive = point_collision_mode::undefined,
                                                .mode_reverse_drive = point_collision_mode::undefined,
                                                .pose = pose_default});

    // 记录坐标系
    frame_id_ = path.header.frame_id;

    // 计算路径上每个点的近似切线角度
    size_t size = ret.size();

#pragma omp parallel for
    for (int i = 0; i < size; i++)
    {
        // 赋值点坐标
        ret[i].pose = path.poses[i];

        // 往前计算
        if (i < size - 2)
        {
            vector<geometry_msgs::msg::Pose> forward_points;

            forward_points.clear();

            for (int j = 1; j <= min(5, (int)(size - i - 2)); j += 1)
            {
                forward_points.push_back(path.poses[i + j].pose);
            }

            ret[i].pose.pose.orientation =
                quaternion_msg_from_yaw(
                    calc_path_point_orientation(ret[i].pose.pose, forward_points));
        }
        else if (i != size - 1)
        {
            ret[i].pose.pose.orientation = ret[i - 1].pose.pose.orientation;
        }
    }

    // 获取地图
    if (frame_id_ == LOCALIZATION_MAP)
    {
        map_ = openmover::wait_for_message<nav_msgs::msg::OccupancyGrid>(node_, "occupancy_grid", rclcpp::QoS(1), std::chrono::seconds(2));
    }

#pragma omp parallel for
    // 推算路径点是否为狭窄空间
    for (int i = 0; i < size - 1; i += sampling_ratio)
    {
        // 如果为 odom 坐标系，则无法检测，考虑到为小范围导航，使用智能策略
        if (frame_id_ == LOCALIZATION_MAP && map_ != NULL)
        {
            // 在这里识别正向运行的狭窄空间
            if (is_footprint_has_occupied_point(
                    map_, footprint, ret[i].pose, stop_distance, false, sampling_ratio,
                    obstacle_detection_area_padding_ratio))
            {
                ret[i].mode_forward_drive = point_collision_mode::narrow;
            }
            else
            {
                ret[i].mode_forward_drive = point_collision_mode::normal;
            }

            // 在这里识别反向运行的狭窄空间
            if (is_footprint_has_occupied_point(
                    map_, footprint, ret[i].pose, stop_distance, true, sampling_ratio,
                    obstacle_detection_area_padding_ratio))
            {
                ret[i].mode_reverse_drive = point_collision_mode::narrow;
            }
            else
            {
                ret[i].mode_reverse_drive = point_collision_mode::normal;
            }
        }
        else
        {
            ret[i].mode_forward_drive = point_collision_mode::narrow;
            ret[i].mode_reverse_drive = point_collision_mode::narrow;
        }

        // 插补未采样点
        for (int j = 1; j <= min(sampling_ratio - 1, (int)size - i - 2); j++)
        {
            ret[i + j].mode_forward_drive = ret[i].mode_forward_drive;
            ret[i + j].mode_reverse_drive = ret[i].mode_reverse_drive;
        }
    }

    // 处理狭窄空间扩展区域
    point_collision_mode last_collision_mode = point_collision_mode::undefined;

    // 前向轨迹
    for (int i = 0; i < size;)
    {
        if (last_collision_mode == point_collision_mode::narrow &&
            ret[i].mode_forward_drive == point_collision_mode::normal)
        {
            // 向普通区域扩展
            for (int j = i; j < min((int)size, i + narrow_section_padding); j++)
            {
                ret[j].mode_forward_drive = point_collision_mode::narrow;
            }

            last_collision_mode = point_collision_mode::normal;

            i += narrow_section_padding;
        }
        else if (last_collision_mode == point_collision_mode::normal &&
                 ret[i].mode_forward_drive == point_collision_mode::narrow)
        {
            // 向普通区域扩展
            for (int j = i; j >= max(0, i - narrow_section_padding); j--)
            {
                ret[j].mode_forward_drive = point_collision_mode::narrow;
            }

            last_collision_mode = point_collision_mode::narrow;

            i++;
        }
        else
        {
            last_collision_mode = ret[i].mode_forward_drive;

            i++;
        }
    }

    // 反向轨迹
    last_collision_mode = point_collision_mode::undefined;

    for (int i = 0; i < size;)
    {
        if (last_collision_mode == point_collision_mode::narrow &&
            ret[i].mode_reverse_drive == point_collision_mode::normal)
        {
            // 向普通区域扩展
            for (int j = i; j < min((int)size, i + narrow_section_padding); j++)
            {
                ret[j].mode_reverse_drive = point_collision_mode::narrow;
            }

            last_collision_mode = point_collision_mode::normal;

            i += narrow_section_padding;
        }
        else if (last_collision_mode == point_collision_mode::normal &&
                 ret[i].mode_reverse_drive == point_collision_mode::narrow)
        {
            // 向普通区域扩展
            for (int j = i; j >= max(0, i - narrow_section_padding); j--)
            {
                ret[j].mode_reverse_drive = point_collision_mode::narrow;
            }

            last_collision_mode = point_collision_mode::narrow;

            i++;
        }
        else
        {
            last_collision_mode = ret[i].mode_forward_drive;

            i++;
        }
    }

    // 目标点强制为智能模式
    ret[size - 1].mode_forward_drive = point_collision_mode::narrow;
    ret[size - 1].mode_reverse_drive = point_collision_mode::narrow;

#if PC_DEBUG
    // 可视化近似切线轨迹
    nav_msgs::msg::Path path_msg;
    path_msg.header.frame_id = frame_id_;
    path_msg.header.stamp = (node_ ? node_->now() : rclcpp::Clock(RCL_ROS_TIME).now());

    size = ret.size();

    for (int i = 0; i < size; i++)
    {
        path_msg.poses.push_back(ret[i].pose);
        path_msg.poses[i].header.frame_id = frame_id_;
        path_msg.poses[i].header.stamp = (node_ ? node_->now() : rclcpp::Clock(RCL_ROS_TIME).now());
    }

    if (path_with_orientation_pub_) path_with_orientation_pub_->publish(path_msg);

    // 可视化区域标记
    visualization_msgs::msg::MarkerArray marker_array_msgs;

    marker_array_msgs.markers.clear();

    static int last_marker_array_size = size;

    for (int i = 0; i < max((int)size, last_marker_array_size); i++)
    {
        visualization_msgs::msg::Marker marker;
        marker.header.frame_id = frame_id_;
        marker.header.stamp = (node_ ? node_->now() : rclcpp::Clock(RCL_ROS_TIME).now());
        marker.ns = frame_id_;
        marker.action = i >= size ? marker.DELETE : marker.ADD;
        marker.id = i;
        marker.type = marker.SPHERE;
        marker.color.a = 1;
        marker.color.r =
            (ret[i].mode_forward_drive == point_collision_mode::normal)
                ? 1
                : 0;
        marker.color.g =
            (ret[i].mode_forward_drive == point_collision_mode::normal)
                ? 0
                : 1;
        marker.scale.x = i >= size ? 0 : 0.02;
        marker.scale.y = i >= size ? 0 : 0.02;
        marker.scale.z = i >= size ? 0 : 0.02;
        marker.pose = ret[i].pose.pose;

        marker_array_msgs.markers.push_back(marker);
    }

    last_marker_array_size = size;

    if (visual_marker_array_pub_) visual_marker_array_pub_->publish(marker_array_msgs);
#endif

    return ret;
}