#include <navigation/utils/collision_checker/collision_checker.h>

collision_checker::collision_checker()
{
    footprint_transformed_pub_ = node_handle_.advertise<geometry_msgs::PolygonStamped>("footprint_transformed", 1);
    obstacle_lines_pub_ = node_handle_.advertise<visualization_msgs::MarkerArray>("obstacle_lines", 1);
}

collision_checker::~collision_checker()
{
    std::cout << "collision checker stopped." << std::endl;
}

tuple<bool, vector<float>> collision_checker::check(geometry_msgs::PoseWithCovarianceStamped &pose,
                                                    geometry_msgs::PoseWithCovarianceStamped &obstacle_pose,
                                                    geometry_msgs::Polygon &footprint,
                                                    nav_msgs::Path &trajectory,
                                                    openmover_msgs::obstacle &obstacle,
                                                    int trajectory_sampling_ratio,
                                                    bool visualization)
{
    tuple<bool, vector<float>> ret;

    get<0>(ret) = false;
    get<1>(ret).clear();

    frame_id_ = pose.header.frame_id;

    // 创建障碍线
    auto obstacle_line_info = create_obstacle_lines(pose, footprint, obstacle);

    if (visualization)
    {
        // 可视化
        static vector<int> last_marker_ids;
        visualization_msgs::MarkerArray marker_array;
        int id = 0;

        // 清除上一次的标记
        visualization_msgs::MarkerArray clear_markers;

        for (const auto &id : last_marker_ids)
        {
            visualization_msgs::Marker delete_marker;
            delete_marker.header.frame_id = pose.header.frame_id;
            delete_marker.header.stamp = ros::Time::now();
            delete_marker.ns = "obstacle_lines";
            delete_marker.id = id;
            delete_marker.action = visualization_msgs::Marker::DELETE;

            clear_markers.markers.push_back(delete_marker);
        }

        obstacle_lines_pub_.publish(clear_markers);

        // 发布当前的标记
        last_marker_ids.clear();

        for (const auto &line : get<0>(obstacle_line_info))
        {
            last_marker_ids.push_back(id);

            visualization_msgs::Marker line_marker;
            line_marker.header.frame_id = pose.header.frame_id;
            line_marker.header.stamp = ros::Time::now();
            line_marker.ns = "obstacle_lines";
            line_marker.id = id++;
            line_marker.type = visualization_msgs::Marker::LINE_STRIP;
            line_marker.action = visualization_msgs::Marker::ADD;

            line_marker.scale.x = 0.01;
            line_marker.color.r = 0.0;
            line_marker.color.g = 0.0;
            line_marker.color.b = 1.0;
            line_marker.color.a = 1.0;

            geometry_msgs::Point p_start, p_end;
            p_start.x = line.p0.x;
            p_start.y = line.p0.y;
            p_start.z = line.p0.z;
            p_end.x = line.p1.x;
            p_end.y = line.p1.y;
            p_end.z = line.p1.z;

            line_marker.points.push_back(p_start);
            line_marker.points.push_back(p_end);

            marker_array.markers.push_back(line_marker);
        }

        obstacle_lines_pub_.publish(marker_array);
    }

    // 采样轨迹
    size_t size = trajectory.poses.size();
    float min_dist_forward = INFINITY;
    float min_dist_rear = INFINITY;
    float min_dist_left = INFINITY;
    float min_dist_right = INFINITY;

    for (int i = 0; i < size; i += trajectory_sampling_ratio)
    {
        // 变换足迹
        geometry_msgs::PoseWithCovarianceStamped traj_pose;
        traj_pose.header.frame_id = frame_id_;
        traj_pose.pose.pose = trajectory.poses[i].pose;

        geometry_msgs::Polygon footprint_transformed = transform_footprint(traj_pose, footprint);

        // 计算足迹的中心点
        geometry_msgs::Point32 footprint_center = calculate_polygon_center(footprint_transformed);

        if (visualization)
        {
            // 可视化
            geometry_msgs::PolygonStamped footprint_msg;

            footprint_msg.header.stamp = ros::Time::now();
            footprint_msg.header.frame_id = frame_id_;
            footprint_msg.polygon = footprint_transformed;

            footprint_transformed_pub_.publish(footprint_msg);
        }

        // 计算前后左右距离障碍物最近距离
        for (const auto &line : get<0>(obstacle_line_info))
        {
            // 计算线段的中心点
            geometry_msgs::Point32 line_center = calculate_line_center(line);

            // 计算距离并存储
            float distance = calculate_distance(footprint_center, line_center);

            if (line.type == obstacle_line_type::FRONT)
            {
                min_dist_forward = min(min_dist_forward, distance);
            }
            else if (line.type == obstacle_line_type::REAR)
            {
                min_dist_rear = min(min_dist_forward, distance);
            }
            else if (line.type == obstacle_line_type::LEFT)
            {
                min_dist_left = min(min_dist_left, distance);
            }
            else if (line.type == obstacle_line_type::RIGHT)
            {
                min_dist_right = min(min_dist_right, distance);
            }
        }

        // 在此检测冲突
        if (is_line_intersect_rect(footprint_transformed, get<0>(obstacle_line_info)))
        {
            get<0>(ret) = true;

            break;
        }
    }

    get<1>(ret).push_back(min_dist_forward);
    get<1>(ret).push_back(min_dist_rear);
    get<1>(ret).push_back(min_dist_left);
    get<1>(ret).push_back(min_dist_right);

    return ret;
}

bool collision_checker::check(geometry_msgs::PoseWithCovarianceStamped &pose,
                              geometry_msgs::PoseWithCovarianceStamped &obstacle_pose,
                              geometry_msgs::Polygon &footprint,
                              vector<geometry_msgs::PoseStamped> &path,
                              int current_point_index,
                              float sim_time, float max_vel_x,
                              openmover_msgs::obstacle &obstacle,
                              int trajectory_sampling_ratio)
{
    bool ret = false;

    frame_id_ = pose.header.frame_id;

    // 创建障碍线
    auto obstacle_line_info = create_obstacle_lines(obstacle_pose, footprint, obstacle);

    // 采样路径
    size_t size = path.size();

    for (int i = current_point_index; i < size; i += trajectory_sampling_ratio)
    {
        // 计算至前向仿真时间
        if (calculate_distance(path[current_point_index].pose,
                               path[i].pose) > sim_time * max_vel_x)
        {
            break;
        }

        // 变换足迹
        geometry_msgs::PoseWithCovarianceStamped path_pose;
        path_pose.header.frame_id = frame_id_;
        path_pose.pose.pose = path[i].pose;

        geometry_msgs::Polygon footprint_transformed = transform_footprint(path_pose, footprint);

        // 在此检测冲突
        if (is_line_intersect_rect(footprint_transformed, get<0>(obstacle_line_info)))
        {
            ret = true;

            break;
        }
    }

    return ret;
}