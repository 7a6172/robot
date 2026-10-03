#include <navigation/utils/global_planner/planner_with_costmap.h>

tuple<bool, vector<geometry_msgs::msg::PoseStamped>, vector<geometry_msgs::msg::PoseStamped>> planner_with_costmap::plan(geometry_msgs::msg::PoseStamped &start, geometry_msgs::msg::PoseStamped &goal,
                                                                                                               float min_dist_to_obs,
                                                                                                               bool optimize,
                                                                                                               int sampling_grid_dist,
                                                                                                               bool polyline,
                                                                                                               float polyline_sample_max_dist,
                                                                                                               int polyline_sample_step,
                                                                                                               int occupied_threshold)
{
    nav_msgs::msg::OccupancyGrid grid_empty;
    grid_empty.data.clear();

    return plan(start, goal, grid_empty, min_dist_to_obs, optimize, sampling_grid_dist, polyline, polyline_sample_max_dist, polyline_sample_step, occupied_threshold);
}

tuple<bool, vector<geometry_msgs::msg::PoseStamped>, vector<geometry_msgs::msg::PoseStamped>> planner_with_costmap::plan(geometry_msgs::msg::PoseStamped &start, geometry_msgs::msg::PoseStamped &goal,
                                                                                                               nav_msgs::msg::OccupancyGrid &grid,
                                                                                                               float min_dist_to_obs,
                                                                                                               bool optimize,
                                                                                                               int sampling_grid_dist,
                                                                                                               bool polyline,
                                                                                                               float polyline_sample_max_dist,
                                                                                                               int polyline_sample_step,
                                                                                                               int occupied_threshold)
{
    vector<PoseStamped> path;
    vector<PoseStamped> polyline_path;

    start.header.frame_id = LOCALIZATION_MAP;
    goal.header.frame_id = LOCALIZATION_MAP;

    // 判断 costmap 是否可用
    while (!cmap_->isCurrent())
    {
        rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::duration<double>(COST_MAP_WAIT_UPDATE_DURATION)));
    }

    // 判断是否已等待代价地图
    if ((node_ ? node_->now() : rclcpp::Clock(RCL_ROS_TIME).now()) - time_ < rclcpp::Duration::from_seconds(COST_MAP_WAIT_DURATION))
    {
        rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::duration<double>(COST_MAP_WAIT_DURATION)));
    }

    bool success = make_plan(start, goal, 0.0f, path, polyline_path, grid, min_dist_to_obs, optimize, sampling_grid_dist,
                             polyline, polyline_sample_max_dist, polyline_sample_step, occupied_threshold);

    return make_tuple(success, path, polyline_path);
}

tuple<bool, unsigned int, unsigned int> planner_with_costmap::world_to_map(geometry_msgs::msg::Pose pose)
{
    tuple<bool, unsigned int, unsigned int> ret = {false, 0, 0};

    bool success = false;
    unsigned int mx = 0;
    unsigned int my = 0;

    if (cmap_ != NULL && cmap_->isCurrent() && cmap_->getCostmap()->getCharMap() != NULL)
    {
        success = cmap_->getCostmap()->worldToMap(pose.position.x, pose.position.y, mx, my);
    }

    ret = {success, mx, my};

    return ret;
}

tuple<int, int> planner_with_costmap::get_edge_point_index_in_map(
    geometry_msgs::msg::PoseWithCovarianceStamped pose, vector<geometry_msgs::msg::PoseStamped> path, int robot_pose_index)
{
    tuple<int, int> ret = {-1, -1};

    if (robot_pose_index < 0)
    {
        robot_pose_index_finder finder;
        finder.set_path(path);
        robot_pose_index = finder.get_index(pose);
    }

    int index_forward = -1;
    int index_reverse = -1;

    for (int i = robot_pose_index; i < path.size(); i++)
    {
        if (!get<0>(world_to_map(path[i].pose)))
        {
            index_forward = i < 10 ? 0 : i - 10;

            break;
        }
    }

    for (int i = robot_pose_index; i >= 0; i--)
    {
        if (!get<0>(world_to_map(path[i].pose)))
        {
            index_reverse = (i >= path.size() - 10) ? (path.size() - 1) : (i + 10);

            break;
        }
    }

    ret = {index_forward, index_reverse};

    return ret;
}

void robot_pose_index_finder::find_closest_point(const geometry_msgs::msg::PoseWithCovarianceStamped &robot_pose,
                                                 const std::vector<geometry_msgs::msg::PoseStamped> &path,
                                                 int start, int end, closet_point_info &result)
{
    result.distance = std::numeric_limits<double>::max();

    for (int i = start; i < end; i++)
    {
        double distance = calculate_distance(robot_pose.pose.pose, path[i].pose);

        if (distance < result.distance)
        {
            result.distance = distance;
            result.index = i;
        }
    }
}

void robot_pose_index_finder::set_path(vector<geometry_msgs::msg::PoseStamped> path, bool use_kdtree)
{
    path_ = path;
    use_kdtree_ = use_kdtree;

    if (use_kdtree_ && path_.size() > 0)
    {
        cloud_->clear();

        for (int i = 0; i < path_.size(); ++i)
        {
            cloud_->push_back(pcl::PointXYZ(
                path_[i].pose.position.x,
                path_[i].pose.position.y,
                path_[i].pose.position.z));
        }

        kdtree_.setInputCloud(cloud_);
    }

    empty_ = path_.size() <= 0;
}

int robot_pose_index_finder::get_index(geometry_msgs::msg::PoseWithCovarianceStamped robot_pose, int start, int end, int thread_num)
{
    int ret = -1;

    if (!empty_)
    {
        // kdtree 模式
        if (use_kdtree_)
        {
            pcl::PointXYZ search_point(
                robot_pose.pose.pose.position.x,
                robot_pose.pose.pose.position.y,
                robot_pose.pose.pose.position.z);

            std::vector<int> pointIdxNKNSearch(1);
            std::vector<float> pointNKNSquaredDistance(1);

            if (kdtree_.nearestKSearch(search_point, 1, pointIdxNKNSearch, pointNKNSquaredDistance) > 0)
            {
                ret = pointIdxNKNSearch[0];
            }
        }
        // 多线程查找模式
        else
        {
            if (start < 0)
            {
                start = 0;
            }

            if (end < 0 || end >= path_.size())
            {
                end = path_.size();
            }

            int num_points = end - start;
            thread_num = min(num_points, thread_num);
            int points_per_thread = num_points / thread_num;
            std::vector<closet_point_info> results(thread_num, {-1, std::numeric_limits<double>::max()});

            std::vector<std::thread> threads;

            for (int i = 0; i < thread_num; i++)
            {
                int local_start = start + i * points_per_thread;
                int local_end = (i == thread_num - 1) ? end : (local_start + points_per_thread);

                threads.emplace_back(find_closest_point, std::cref(robot_pose), std::cref(path_), local_start, local_end, std::ref(results[i]));
            }

            for (auto &thread : threads)
            {
                thread.join();
            }

            closet_point_info min_result = results[0];

            for (const auto &result : results)
            {
                if (result.distance < min_result.distance)
                {
                    min_result = result;
                }
            }

            ret = min_result.index;
        }
    }

    return ret;
}