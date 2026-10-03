#include <utils/auto_mapping/global_exploration.h>
#include <utils/topic_utils.h>

namespace global_exploration
{
    global_explorer::global_explorer(const float &min_expand_dist, const float &max_expand_dist, const float &min_dist_to_obs,
                                     const float &frontier_points_min_dist, const float &sensing_radius,
                                     const int &free_threshold, const int &occupied_threshold)
    {
        random_device_ = make_unique<random_device>();
        random_generator_ = make_unique<mt19937>((*random_device_)());
        gen_random_number_ = make_unique<uniform_real_distribution<float>>(0.0f, 1.0f);

        free_threshold_ = free_threshold;
        occupied_threshold_ = occupied_threshold - 1;

        min_expand_dist_ = min_expand_dist;
        max_expand_dist_ = max_expand_dist;
        min_dist_to_obs_ = min_dist_to_obs;
        frontier_points_min_dist_ = frontier_points_min_dist;
        sensing_radius_ = sensing_radius;
    }

    void global_explorer::initialize(rclcpp::Node::SharedPtr node)
    {
        cout << "initializing global exploration..." << endl;

        node_ = node;

        tf_buffer_ = make_unique<tf2_ros::Buffer>(node_->get_clock());
        tf_listener_ = make_unique<tf2_ros::TransformListener>(*tf_buffer_, node_, true);

        for (int i = 0; i < 5; i++)
        {
            try
            {
                tf_map_to_base_link_ = tf_buffer_->lookupTransform(
                    LOCALIZATION_MAP,
                    LOCALIZATION_BASE_LINK,
                    tf2::TimePointZero, tf2::durationFromSec(60.0));
            }
            catch (...)
            {
                cout << "no tf data from map to base_link." << endl;
            }
        }

        try
        {
            auto grid = topic_utils::wait_for_message<nav_msgs::msg::OccupancyGrid>(
                node_.get(), "map", std::chrono::duration<double>(60.0));

            if (grid != NULL)
            {
                map_data_ = *grid;
            }
        }
        catch (...)
        {
            cout << "could not get global map." << endl;

            return;
        }

        int width = map_data_.info.width;
        int height = map_data_.info.height;
        float resolution = map_data_.info.resolution;

        min_dist_to_obs_table_ = calc_min_dist_to_obs_table(map_data_, occupied_threshold_);

        current_map_x_ = width * resolution;
        current_map_y_ = height * resolution;

        float origin_x = map_data_.info.origin.position.x;
        float origin_y = map_data_.info.origin.position.y;
        start_x_ = origin_x + current_map_x_ / 2.0;
        start_y_ = origin_y + current_map_y_ / 2.0;

        map_callback_group_ = node_->create_callback_group(
            rclcpp::CallbackGroupType::MutuallyExclusive, false);

        rclcpp::SubscriptionOptions map_sub_opt;
        map_sub_opt.callback_group = map_callback_group_;

        map_sub_ = node_->create_subscription<nav_msgs::msg::OccupancyGrid>(
            "map",
            rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable(),
            [this](const nav_msgs::msg::OccupancyGrid::ConstSharedPtr msg)
            {
                this->map_callback(msg);
            },
            map_sub_opt);

        map_executor_ = make_unique<rclcpp::executors::SingleThreadedExecutor>();
        map_executor_->add_callback_group(
            map_callback_group_, node_->get_node_base_interface());

        rrt_node_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("global_exploration_nodes", 5);
        rrt_frontier_node_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("global_exploration_frontier_nodes", 5);
        rrt_line_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("global_exploration_lines", 5);

        origin_.x = tf_map_to_base_link_.transform.translation.x;
        origin_.y = tf_map_to_base_link_.transform.translation.y;
        origin_.z = tf_map_to_base_link_.transform.translation.z;

        cout << "robot origin x: " << origin_.x << ", y: " << origin_.y << endl;

        rrt_tree_.indices.push_back(0);
        rrt_tree_.points.push_back(origin_);
        rrt_tree_.prev_indices.push_back(0);
        rrt_tree_.prev_points.push_back(origin_);
        rrt_tree_.next_indices.emplace_back();
        rrt_tree_.next_points.emplace_back();
        rrt_tree_.info_gains.push_back(0.0f);
        rrt_tree_.del_states.push_back(false);

        rtree_points_.clear();
        rtree_points_.emplace_back(origin_.x, origin_.y);
        vector<RTreeValue> initial_data;
        initial_data.emplace_back(rtree_points_.front(), 0);
        rtree_ = bgi::rtree<RTreeValue, bgi::quadratic<16>>(initial_data.begin(), initial_data.end());

        visualization_msgs::msg::Marker node_marker;
        node_marker.header.frame_id = LOCALIZATION_MAP;
        node_marker.header.stamp = node_->now();
        node_marker.ns = "ns_global_nodes";
        node_marker.id = rrt_tree_.indices[0];
        node_marker.type = visualization_msgs::msg::Marker::POINTS;
        node_marker.action = visualization_msgs::msg::Marker::ADD;
        node_marker.scale.x = 0.05;
        node_marker.scale.y = 0.05;
        node_marker.color.r = 1.0;
        node_marker.color.g = 0.0;
        node_marker.color.b = 0.0;
        node_marker.color.a = 1.0;
        node_marker.pose.orientation.w = 1.0;

        geometry_msgs::msg::Point point;
        point.x = rrt_tree_.points[0].x;
        point.y = rrt_tree_.points[0].y;
        point.z = rrt_tree_.points[0].z;

        node_marker.points.push_back(point);

        rrt_node_marker_array_.markers.push_back(node_marker);

        rrt_node_marker_array_pub_->publish(rrt_node_marker_array_);

        rrt_node_marker_array_.markers.clear();

        sampling_ = false;

        rrt_thread_ = thread(&global_explorer::thread_loop, this);

        cout << "global exploration started." << endl;
    }

    void global_explorer::reset()
    {
        cout << "resetting global exploration..." << endl;

        mutex_data_.lock();

        rrt_tree_.indices.clear();
        rrt_tree_.points.clear();
        rrt_tree_.prev_indices.clear();
        rrt_tree_.prev_points.clear();
        rrt_tree_.next_indices.clear();
        rrt_tree_.next_points.clear();
        rrt_tree_.info_gains.clear();
        rrt_tree_.del_states.clear();

        frontier_points_.indices.clear();
        frontier_points_.points.clear();
        frontier_points_.prev_indices.clear();
        frontier_points_.prev_points.clear();
        frontier_points_.next_indices.clear();
        frontier_points_.next_points.clear();
        frontier_points_.info_gains.clear();
        frontier_points_.del_states.clear();

        node_index_ = 0;

        rrt_tree_.indices.push_back(0);
        rrt_tree_.points.push_back(origin_);
        rrt_tree_.prev_indices.push_back(0);
        rrt_tree_.prev_points.push_back(origin_);
        rrt_tree_.next_indices.emplace_back();
        rrt_tree_.next_points.emplace_back();
        rrt_tree_.info_gains.push_back(0.0f);
        rrt_tree_.del_states.push_back(false);

        rtree_points_.clear();
        rtree_points_.emplace_back(origin_.x, origin_.y);
        vector<RTreeValue> initial_data;
        initial_data.emplace_back(rtree_points_.front(), 0);
        rtree_ = bgi::rtree<RTreeValue, bgi::quadratic<16>>(initial_data.begin(), initial_data.end());

        rrt_frontier_node_marker_array_.markers.clear();

        visualization_msgs::msg::Marker frontier_node_marker;
        frontier_node_marker.header.frame_id = LOCALIZATION_MAP;
        frontier_node_marker.header.stamp = node_->now();
        frontier_node_marker.ns = "ns_global_frontier_nodes";
        frontier_node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);

        rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

        rrt_frontier_node_marker_array_.markers.clear();

        sampling_ = true;

        mutex_data_.unlock();

        cout << "global exploration reset." << endl;
    }

    void global_explorer::stop()
    {
        cout << "stopping global exploration..." << endl;

        mutex_data_.lock();

        sampling_ = false;

        mutex_data_.unlock();

        cout << "global exploration stopped." << endl;
    }

    void global_explorer::map_callback(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr &msg)
    {
        mutex_data_.lock();

        map_data_ = *msg;

        int width = map_data_.info.width;
        int height = map_data_.info.height;
        float resolution = map_data_.info.resolution;

        min_dist_to_obs_table_ = calc_min_dist_to_obs_table(map_data_, occupied_threshold_);

        current_map_x_ = width * resolution;
        current_map_y_ = height * resolution;

        float origin_x = map_data_.info.origin.position.x;
        float origin_y = map_data_.info.origin.position.y;
        start_x_ = origin_x + current_map_x_ / 2.0;
        start_y_ = origin_y + current_map_y_ / 2.0;

        rrt_nodes frontier_points_final;

        size_t size = frontier_points_.indices.size();

        for (int i = 0; i < size; i++)
        {
            auto check_result = exploration_check_segment_type(frontier_points_.prev_points[i], frontier_points_.points[i], 8,
                                                               min_dist_to_obs_, map_data_, min_dist_to_obs_table_, true,
                                                               free_threshold_, occupied_threshold_);

            if (check_result == exploration_segment_type::NO_COLLISION_WITH_UNKNOW &&
                !is_point_unknow(frontier_points_.prev_points[i], map_data_, free_threshold_, occupied_threshold_) &&
                is_point_unknow(frontier_points_.points[i], map_data_, free_threshold_, occupied_threshold_))
            {
                frontier_points_final.indices.push_back(frontier_points_.indices[i]);
                frontier_points_final.points.push_back(frontier_points_.points[i]);
                frontier_points_final.prev_indices.push_back(frontier_points_.prev_indices[i]);
                frontier_points_final.prev_points.push_back(frontier_points_.prev_points[i]);
                frontier_points_final.next_indices.emplace_back();
                frontier_points_final.next_points.emplace_back();
                frontier_points_final.info_gains.push_back(calc_unknow_area(frontier_points_.points[i], sensing_radius_, map_data_,
                                                                            free_threshold_, occupied_threshold_));
                frontier_points_final.del_states.push_back(false);
            }
        }

        if (frontier_points_final.indices.size() != frontier_points_.indices.size())
        {
            rrt_frontier_node_marker_array_.markers.clear();

            visualization_msgs::msg::Marker frontier_node_marker;
            frontier_node_marker.header.frame_id = LOCALIZATION_MAP;
            frontier_node_marker.header.stamp = node_->now();
            frontier_node_marker.ns = "ns_global_frontier_nodes";
            frontier_node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
            rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);

            rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

            rrt_frontier_node_marker_array_.markers.clear();

            size_t size_final = frontier_points_final.indices.size();

            for (int i = 0; i < size_final; i++)
            {
                frontier_node_marker.header.frame_id = LOCALIZATION_MAP;
                frontier_node_marker.header.stamp = node_->now();
                frontier_node_marker.ns = "ns_global_frontier_nodes";
                frontier_node_marker.id = frontier_points_final.indices[i];
                frontier_node_marker.type = visualization_msgs::msg::Marker::POINTS;
                frontier_node_marker.action = visualization_msgs::msg::Marker::ADD;
                frontier_node_marker.scale.x = 0.1;
                frontier_node_marker.scale.y = 0.1;
                frontier_node_marker.color.r = 1.0;
                frontier_node_marker.color.g = 0.0;
                frontier_node_marker.color.b = 0.0;
                frontier_node_marker.color.a = 1.0;

                geometry_msgs::msg::Point point;
                point.x = frontier_points_final.points[i].x;
                point.y = frontier_points_final.points[i].y;
                point.z = frontier_points_final.points[i].z;

                frontier_node_marker.points.push_back(point);

                rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);
            }

            rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);
        }

        frontier_points_ = frontier_points_final;

        mutex_data_.unlock();
    }

    rrt_nodes global_explorer::get_frontier_points()
    {
        lock_guard<mutex> lock(mutex_data_);

        return frontier_points_;
    }

    float global_explorer::get_rrt_memory_in_mb()
    {
        lock_guard<mutex> lock(mutex_data_);

        size_t n = rrt_tree_.indices.size();

        if (n == 0)
        {
            return 0;
        }

        size_t bytes_per_node =
            sizeof(int) +
            sizeof(geometry_msgs::msg::Point32) +
            sizeof(int) +
            sizeof(geometry_msgs::msg::Point32) +
            sizeof(float) +
            sizeof(bool);

        size_t avg_children = 2;
        size_t next_indices_bytes = avg_children * sizeof(int);
        size_t next_points_bytes = avg_children * sizeof(geometry_msgs::msg::Point32);

        size_t total_bytes_per_node = bytes_per_node + next_indices_bytes + next_points_bytes;
        size_t total_bytes = total_bytes_per_node * n;

        return (float)total_bytes / (1024.0f * 1024.0f);
    }

    void global_explorer::thread_loop()
    {
        rclcpp::Time last_vis_pub_time = node_->now();

        while (rclcpp::ok() && !stop_flag_)
        {
            map_executor_->spin_some();

            if (mutex_data_.try_lock())
            {
                if (!sampling_)
                {
                    mutex_data_.unlock();

                    this_thread::sleep_for(chrono::milliseconds(50));

                    continue;
                }

                geometry_msgs::msg::Point32 sample_point;
                sample_point.x = (generate_random_number() * current_map_x_) - (current_map_x_ / 2.0) + start_x_;
                sample_point.y = (generate_random_number() * current_map_y_) - (current_map_y_ / 2.0) + start_y_;
                sample_point.z = 0;

                tuple<int, geometry_msgs::msg::Point32> nearest_point;

                BGPoint query_pt(sample_point.x, sample_point.y);
                vector<RTreeValue> result;
                rtree_.query(bgi::nearest(query_pt, 1), back_inserter(result));
                get<0>(nearest_point) = result.front().second;
                get<1>(nearest_point) = rrt_tree_.points[get<0>(nearest_point)];

                if (calculate_distance(get<1>(nearest_point), origin_) < 2 * min_dist_to_obs_ ||
                    !is_point_unknow(get<1>(nearest_point), map_data_, -1, -1))
                {
                    float expand_dist = calc_decayed_distance(get<1>(nearest_point),
                                                              map_data_, min_dist_to_obs_table_, min_dist_to_obs_,
                                                              min_expand_dist_, max_expand_dist_);

                    geometry_msgs::msg::Point32 new_point = generate_point(get<1>(nearest_point), sample_point, expand_dist);

                    if (is_point_in_map(new_point, map_data_))
                    {
                        auto check_result = exploration_check_segment_type(get<1>(nearest_point), new_point, 8,
                                                                           min_dist_to_obs_, map_data_, min_dist_to_obs_table_, true,
                                                                           free_threshold_, occupied_threshold_);

                        if (check_result != exploration_segment_type::WITH_COLLISION)
                        {
                            rrt_tree_.indices.push_back(++node_index_);
                            rrt_tree_.points.push_back(new_point);
                            rrt_tree_.prev_indices.push_back(get<0>(nearest_point));
                            rrt_tree_.prev_points.push_back(get<1>(nearest_point));
                            rrt_tree_.next_indices.emplace_back();
                            rrt_tree_.next_points.emplace_back();
                            rrt_tree_.next_indices[get<0>(nearest_point)].push_back(node_index_);
                            rrt_tree_.next_points[get<0>(nearest_point)].push_back(new_point);
                            rrt_tree_.info_gains.push_back(0.0f);
                            rrt_tree_.del_states.push_back(false);

                            rtree_points_.emplace_back(new_point.x, new_point.y);
                            rtree_.insert(make_pair(rtree_points_.back(), node_index_));

                            visualization_msgs::msg::Marker node_marker;
                            node_marker.header.frame_id = LOCALIZATION_MAP;
                            node_marker.header.stamp = node_->now();
                            node_marker.ns = "ns_global_nodes";
                            node_marker.id = node_index_;
                            node_marker.lifetime = rclcpp::Duration::from_seconds(0.2);
                            node_marker.type = visualization_msgs::msg::Marker::POINTS;
                            node_marker.action = visualization_msgs::msg::Marker::ADD;
                            node_marker.scale.x = 0.05;
                            node_marker.scale.y = 0.05;
                            node_marker.color.r = 1.0;
                            node_marker.color.g = 0.0;
                            node_marker.color.b = 0.0;
                            node_marker.color.a = 1.0;
                            node_marker.pose.orientation.w = 1.0;

                            geometry_msgs::msg::Point node_point;
                            node_point.x = new_point.x;
                            node_point.y = new_point.y;
                            node_point.z = new_point.z;

                            node_marker.points.push_back(node_point);

                            rrt_node_marker_array_.markers.push_back(node_marker);

                            visualization_msgs::msg::Marker line_marker;
                            line_marker.header.frame_id = LOCALIZATION_MAP;
                            line_marker.header.stamp = node_->now();
                            line_marker.ns = "ns_global_lines";
                            line_marker.id = node_index_;
                            line_marker.lifetime = rclcpp::Duration::from_seconds(0.2);
                            line_marker.type = visualization_msgs::msg::Marker::LINE_STRIP;
                            line_marker.action = visualization_msgs::msg::Marker::ADD;

                            line_marker.scale.x = 0.02;
                            line_marker.color.r = 1.0;
                            line_marker.color.g = 0.0;
                            line_marker.color.b = 0.0;
                            line_marker.color.a = 1.0;
                            line_marker.pose.orientation.w = 1.0;

                            geometry_msgs::msg::Point start_point, end_point;
                            start_point.x = get<1>(nearest_point).x;
                            start_point.y = get<1>(nearest_point).y;
                            start_point.z = get<1>(nearest_point).z;
                            end_point.x = new_point.x;
                            end_point.y = new_point.y;
                            end_point.z = new_point.z;

                            line_marker.points.push_back(start_point);
                            line_marker.points.push_back(end_point);

                            rrt_line_marker_array_.markers.push_back(line_marker);
                        }

                        if (check_result == exploration_segment_type::NO_COLLISION_WITH_UNKNOW)
                        {
                            if (!is_point_unknow(get<1>(nearest_point), map_data_, free_threshold_, occupied_threshold_) &&
                                is_point_unknow(new_point, map_data_, free_threshold_, occupied_threshold_))
                            {
                                frontier_points_.indices.push_back(node_index_);
                                frontier_points_.points.push_back(new_point);
                                frontier_points_.prev_indices.push_back(get<0>(nearest_point));
                                frontier_points_.prev_points.push_back(get<1>(nearest_point));
                                frontier_points_.next_indices.emplace_back();
                                frontier_points_.next_points.emplace_back();
                                frontier_points_.info_gains.push_back(0.0f);
                                frontier_points_.del_states.push_back(false);

                                auto resample_point_indices = resample_points(frontier_points_.points, frontier_points_.indices,
                                                                              frontier_points_min_dist_);

                                frontier_points_.indices.clear();
                                frontier_points_.points.clear();
                                frontier_points_.prev_indices.clear();
                                frontier_points_.prev_points.clear();
                                frontier_points_.next_indices.clear();
                                frontier_points_.next_points.clear();
                                frontier_points_.info_gains.clear();
                                frontier_points_.del_states.clear();

                                rrt_frontier_node_marker_array_.markers.clear();

                                visualization_msgs::msg::Marker frontier_node_marker;
                                frontier_node_marker.header.frame_id = LOCALIZATION_MAP;
                                frontier_node_marker.header.stamp = node_->now();
                                frontier_node_marker.ns = "ns_global_frontier_nodes";
                                frontier_node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
                                rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);

                                rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

                                rrt_frontier_node_marker_array_.markers.clear();

                                size_t size = resample_point_indices.size();

                                for (int i = 0; i < size; i++)
                                {
                                    frontier_points_.indices.push_back(resample_point_indices[i]);
                                    frontier_points_.points.push_back(rrt_tree_.points[resample_point_indices[i]]);
                                    frontier_points_.prev_indices.push_back(rrt_tree_.prev_indices[resample_point_indices[i]]);
                                    frontier_points_.prev_points.push_back(rrt_tree_.points[rrt_tree_.prev_indices[resample_point_indices[i]]]);
                                    frontier_points_.next_indices.emplace_back();
                                    frontier_points_.next_points.emplace_back();
                                    frontier_points_.info_gains.push_back(calc_unknow_area(rrt_tree_.points[resample_point_indices[i]],
                                                                                           sensing_radius_, map_data_,
                                                                                           free_threshold_, occupied_threshold_));
                                    frontier_points_.del_states.push_back(false);
                                }

                                for (int i = 0; i < size; i++)
                                {
                                    frontier_node_marker.header.frame_id = LOCALIZATION_MAP;
                                    frontier_node_marker.header.stamp = node_->now();
                                    frontier_node_marker.ns = "ns_global_frontier_nodes";
                                    frontier_node_marker.id = frontier_points_.indices[i];
                                    frontier_node_marker.type = visualization_msgs::msg::Marker::POINTS;
                                    frontier_node_marker.action = visualization_msgs::msg::Marker::ADD;
                                    frontier_node_marker.scale.x = 0.1;
                                    frontier_node_marker.scale.y = 0.1;
                                    frontier_node_marker.color.r = 1.0;
                                    frontier_node_marker.color.g = 0.0;
                                    frontier_node_marker.color.b = 0.0;
                                    frontier_node_marker.color.a = 1.0;
                                    frontier_node_marker.pose.orientation.w = 1.0;

                                    geometry_msgs::msg::Point point;
                                    point.x = frontier_points_.points[i].x;
                                    point.y = frontier_points_.points[i].y;
                                    point.z = frontier_points_.points[i].z;

                                    frontier_node_marker.points.push_back(point);

                                    rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);
                                }

                                rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

                                rrt_frontier_node_marker_array_.markers.clear();
                            }
                        }
                    }
                }

                if ((node_->now() - last_vis_pub_time).seconds() >= 0.2)
                {
                    rrt_node_marker_array_pub_->publish(rrt_node_marker_array_);
                    rrt_line_marker_array_pub_->publish(rrt_line_marker_array_);

                    rrt_node_marker_array_.markers.clear();
                    rrt_line_marker_array_.markers.clear();

                    last_vis_pub_time = node_->now();
                }

                mutex_data_.unlock();
            }
            else
            {
                this_thread::sleep_for(chrono::milliseconds(50));
            }
        }
    }

    float global_explorer::generate_random_number()
    {
        return (*gen_random_number_)(*random_generator_);
    }
}